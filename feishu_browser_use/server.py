"""FastAPI server for Feishu Bot webhook + background task worker."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, Response

from feishu_browser_use.account.manager import AccountManager
from feishu_browser_use.account.models import AccountStatus
from feishu_browser_use.config import Settings, get_config
from feishu_browser_use.feishu.bot import FeishuBot
from feishu_browser_use.feishu.client import get_feishu_client
from feishu_browser_use.intent import IntentParser
from feishu_browser_use.policy import PolicyGate
from feishu_browser_use.prompting import PromptRegistry
from feishu_browser_use.task.executor import TaskExecutor
from feishu_browser_use.task.models import Attachment, Task, TaskStatus
from feishu_browser_use.task.pool import TaskExecutorPool
from feishu_browser_use.task.queue import TaskQueue

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Globals — initialized in lifespan
# ---------------------------------------------------------------------------

_config: Settings = get_config()
_task_queue: TaskQueue = None  # type: ignore[assignment]
_account_manager: AccountManager = None  # type: ignore[assignment]
_feishu_bot: FeishuBot = None  # type: ignore[assignment]
_executor: TaskExecutor = None  # type: ignore[assignment]
_pool: TaskExecutorPool = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
	global _config, _task_queue, _account_manager, _feishu_bot, _executor, _pool

	_config = get_config()

	# Initialize Feishu client + bot
	client = get_feishu_client()
	_feishu_bot = FeishuBot(client)

	# Initialize task queue
	_task_queue = TaskQueue(db_path=_config.TASK_DB_PATH)
	await _task_queue.start()

	# Initialize account manager
	_account_manager = AccountManager(
		db_path=_config.TASK_DB_PATH,
		profiles_base_dir=_config.PROFILES_DIR,
	)
	await _account_manager.start()

	# Initialize executor + pool
	_executor = TaskExecutor(
		config=_config,
		queue=_task_queue,
		feishu_bot=_feishu_bot,
		account_manager=_account_manager,
	)
	_pool = TaskExecutorPool(
		executor=_executor,
		max_concurrent=_config.MAX_CONCURRENT_TASKS,
	)

	# Start background worker
	worker = asyncio.create_task(_worker_loop())

	logger.info("Server started — port=%s, max_concurrent=%s", _config.SERVER_PORT, _config.MAX_CONCURRENT_TASKS)
	yield

	# Shutdown
	worker.cancel()
	await _pool.shutdown()
	await _task_queue.close()
	await _account_manager.close()
	logger.info("Server stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Feishu Browser Use", lifespan=lifespan)


# Health check
@app.get("/healthz")
async def healthz():
	return {"status": "ok", "pending_tasks": _pool.pending_count()}


# ---------------------------------------------------------------------------
# Feishu webhook challenge (URL verification)
# ---------------------------------------------------------------------------

@app.post("/feishu/webhook")
async def feishu_webhook(request: Request) -> Response:
	"""Handle Feishu event subscription callbacks and card actions."""
	body = await request.json()

	# 1) URL verification challenge
	if "challenge" in body:
		return Response(
			content=json.dumps({"challenge": body["challenge"]}),
			media_type="application/json",
		)

	# 2) Card action callback (审批按钮等)
	if "action" in body:
		return await _handle_card_action(body)

	# 3) Event callback v2.0 (wrapped in "header" + "event")
	header = body.get("header", {})
	event_type = header.get("event_type", "")
	tenant_key = header.get("tenant_key", "")
	event = body.get("event", {})

	logger.info("Feishu event received: type=%s", event_type)

	if event_type == "im.message.receive_v1":
		try:
			await _handle_message_event(event, tenant_key)
		except Exception:
			logger.exception("Error handling message event")

	elif event_type == "card.action.trigger":
		try:
			await _handle_card_action_event(event)
		except Exception:
			logger.exception("Error handling card action event")

	return Response(
		content=json.dumps({"code": 0}),
		media_type="application/json",
	)


# ---------------------------------------------------------------------------
# Card action handler (审批回调)
# ---------------------------------------------------------------------------

async def _handle_card_action_event(event: dict) -> None:
	"""Handle card.action.trigger event from Feishu event subscription.

	Feishu sends card button clicks as event_type=card.action.trigger
	with the action data nested inside event.action.value.
	"""
	action = event.get("action", {})
	value = action.get("value", {})
	action_type = value.get("action")
	chat_id = event.get("context", {}).get("open_chat_id", "")

	logger.info("Card action event: type=%s, value=%s, chat_id=%s", action_type, value, chat_id)

	if not action_type:
		return

	# --- Account management actions ---
	if action_type == "account_login":
		account_id = value.get("account_id")
		if account_id and chat_id:
			asyncio.create_task(_run_login_flow(account_id, chat_id))
			await _notify(chat_id, "🔐 正在打开浏览器登录...")
		return

	if action_type == "account_delete":
		account_id = value.get("account_id")
		account_name = value.get("name", "")
		if account_id:
			deleted = await _account_manager.delete_account(account_id)
			if deleted:
				await _notify(chat_id, f"🗑️ 已删除账号: {account_name}")
			else:
				await _notify(chat_id, f"⚠️ 账号不存在: {account_name}")
		return

	if action_type == "account_add":
		await _notify(chat_id, '请发送: 登录 <平台> <账号名>\n例如: 登录 美团 江湖饭焗')
		return

	if action_type == "account_refresh":
		if chat_id:
			accounts = await _account_manager.get_all_accounts()
			card = _feishu_bot.build_account_card(accounts)
			await _feishu_bot.send_card(chat_id, card)
		return

	# --- Task actions ---
	task_id = value.get("task_id")

	if action_type == "retry" and task_id:
		# Re-submit the task for execution
		task = await _task_queue.get_task(task_id)
		if task:
			# Create a new task with all metadata from original
			new_task = Task(
				user_id=task.user_id,
				chat_id=task.chat_id,
				message_id=task.message_id,
				tenant_key=task.tenant_key,
				raw_text=task.raw_text,
				platform=task.platform,
				instruction=task.instruction,
				account_id=task.account_id,
				intent=task.intent,
				intent_target=task.intent_target,
				intent_params=task.intent_params,
				intent_confidence=task.intent_confidence,
				prompt_version=task.prompt_version,
				policy_status=task.policy_status,
				policy_reason=task.policy_reason,
				allowed_domains=task.allowed_domains,
			)
			await _task_queue.submit(new_task)
			await _notify(chat_id, f"🔄 任务已重新提交\n新ID: {new_task.id[:8]}")
		return

	if action_type == "cancel" and task_id:
		await _task_queue.cancel(task_id)
		await _pool.cancel(task_id)
		await _notify(chat_id, "🛑 已取消")
		return


async def _handle_card_action(body: dict) -> Response:
	"""Handle legacy card action callbacks (direct action in body)."""
	action = body.get("action", {})
	value = action.get("value", {})
	action_type = value.get("action")
	task_id = value.get("task_id")

	logger.info("Card action: type=%s, task_id=%s, value=%s", action_type, task_id, value)

	# --- Task actions ---
	if action_type == "retry" and task_id:
		task = await _task_queue.get_task(task_id)
		if task:
			new_task = Task(
				user_id=task.user_id,
				chat_id=task.chat_id,
				message_id=task.message_id,
				tenant_key=task.tenant_key,
				raw_text=task.raw_text,
				platform=task.platform,
				instruction=task.instruction,
				account_id=task.account_id,
				intent=task.intent,
				intent_target=task.intent_target,
				intent_params=task.intent_params,
				intent_confidence=task.intent_confidence,
				prompt_version=task.prompt_version,
				policy_status=task.policy_status,
				policy_reason=task.policy_reason,
				allowed_domains=task.allowed_domains,
			)
			await _task_queue.submit(new_task)
			return _card_response("success", f"已重新提交: {new_task.id[:8]}")

	if action_type == "cancel" and task_id:
		await _task_queue.cancel(task_id)
		await _pool.cancel(task_id)
		return _card_response("info", "已取消")

	# --- Account management actions ---
	if action_type == "account_login":
		account_id = value.get("account_id")
		chat_id = body.get("open_chat_id") or body.get("context", {}).get("open_chat_id", "")
		if account_id and chat_id:
			asyncio.create_task(_run_login_flow(account_id, chat_id))
			return _card_response("success", "正在打开浏览器登录...")
		return _card_response("warning", "缺少参数")

	if action_type == "account_delete":
		account_id = value.get("account_id")
		account_name = value.get("name", "")
		if account_id:
			await _account_manager.delete_account(account_id)
			return _card_response("info", f"已删除账号: {account_name}")
		return _card_response("warning", "缺少参数")

	if action_type == "account_add":
		return _card_response("info", '请发送: 登录 <平台> <账号名>\n例如: 登录 美团 朝阳店')

	if action_type == "account_refresh":
		# Return updated account list card
		chat_id = body.get("open_chat_id") or body.get("context", {}).get("open_chat_id", "")
		if chat_id:
			accounts = await _account_manager.get_all_accounts()
			card = _feishu_bot.build_account_card(accounts)
			await _feishu_bot.send_card(chat_id, card)
			return _card_response("success", "已刷新")
		return _card_response("warning", "无法获取聊天ID")

	return Response(
		content=json.dumps({"code": 0}),
		media_type="application/json",
	)


def _card_response(toast_type: str, content: str) -> Response:
	"""Helper to build a card action toast response."""
	return Response(
		content=json.dumps({"toast": {"type": toast_type, "content": content}}),
		media_type="application/json",
	)


# ---------------------------------------------------------------------------
# Message event handler
# ---------------------------------------------------------------------------

async def _handle_message_event(event: dict, tenant_key: str = "") -> None:
	"""Handle an incoming Feishu message event."""
	message = event.get("message", {})
	chat_id = message.get("chat_id", "")
	sender = event.get("sender", {}).get("sender_id", {})
	user_id = sender.get("open_id", "")
	msg_type = message.get("message_type", "")
	message_id = message.get("message_id", "")

	# Persist attachments for future image/table-driven operations.
	if msg_type != "text":
		await _handle_attachment_message(
			msg_type=msg_type,
			content_str=message.get("content", "{}"),
			tenant_key=tenant_key,
			chat_id=chat_id,
			message_id=message_id,
			user_id=user_id,
		)
		return

	content_str = message.get("content", "{}")
	content = json.loads(content_str)
	text = content.get("text", "").strip()

	# Strip Feishu @mention tags
	# Format 1: @_user_1, @_all
	# Format 2: <at user_id="xxx">name</at>
	text = re.sub(r"@_\w+\s*", "", text)
	text = re.sub(r"<at\s+user_id=[^>]*>[^<]*</at>\s*", "", text)
	text = text.strip()

	if not text:
		return

	logger.info("Text message: user=%s, text=%r", user_id, text)

	# Try to handle as a special command first
	if await _handle_special_command(text, user_id, chat_id, message_id):
		return

	# Parse message into platform + instruction + account
	platform, instruction, account = await _parse_message_with_account(text, user_id)

	if not instruction:
		await _feishu_bot.reply_text(message_id, "无法理解指令。请发送如：\n朝阳店 美团 搜索咖啡\n或：登录 美团 朝阳店")
		return

	parsed_intent = IntentParser().parse(
		raw_text=text,
		platform=platform,
		instruction=instruction,
	)
	policy_decision = PolicyGate().evaluate(
		raw_text=text,
		platform=platform,
		instruction=instruction,
	)
	if policy_decision.status == "blocked":
		await _feishu_bot.reply_text(
			message_id,
			f"⛔ 指令已拦截\n原因：{policy_decision.reason}\n请使用已支持的商家后台平台和账号。",
		)
		return

	if policy_decision.status == "needs_confirmation":
		await _feishu_bot.reply_text(
			message_id,
			f"⚠️ 该指令属于高风险操作，需要二次确认后执行。\n原因：{policy_decision.reason}\n当前版本暂未开放确认执行。",
		)
		return

	# Build task
	task = Task(
		user_id=user_id,
		chat_id=chat_id,
		message_id=message_id,
		tenant_key=tenant_key,
		raw_text=text,
		platform=platform,
		instruction=instruction,
		account_id=account.id if account else None,
		intent=parsed_intent.intent,
		intent_target=parsed_intent.target,
		intent_params=parsed_intent.params,
		intent_confidence=parsed_intent.confidence,
		prompt_version=PromptRegistry.VERSION,
		policy_status=policy_decision.status,
		policy_reason=policy_decision.reason,
		allowed_domains=policy_decision.allowed_domains,
	)

	await _task_queue.submit(task)

	task_card_message_id = await _feishu_bot.reply_task_card(message_id, task)
	if task_card_message_id:
		await _task_queue.set_task_card_message_id(task.id, task_card_message_id)


async def _handle_attachment_message(
	msg_type: str,
	content_str: str,
	tenant_key: str,
	chat_id: str,
	message_id: str,
	user_id: str,
) -> None:
	"""Store Feishu image/file attachment metadata for future task execution."""
	if msg_type not in {"image", "file"}:
		return

	try:
		content = json.loads(content_str or "{}")
	except json.JSONDecodeError:
		content = {}

	if msg_type == "image":
		attachment = Attachment(
			tenant_key=tenant_key,
			chat_id=chat_id,
			message_id=message_id,
			uploaded_by_user_id=user_id,
			file_type="image",
			file_name=content.get("file_name") or "image",
			mime_type=content.get("mime_type") or "image/*",
			feishu_file_key=content.get("image_key"),
			size_bytes=content.get("file_size"),
			status="stored",
		)
		await _task_queue.add_attachment(attachment)
		await _feishu_bot.reply_text(
			message_id,
			f"📎 已记录图片附件：{attachment.id[:8]}\n当前版本仅保存附件元数据，后续会用于商户图片更新任务。",
		)
		return

	attachment = Attachment(
		tenant_key=tenant_key,
		chat_id=chat_id,
		message_id=message_id,
		uploaded_by_user_id=user_id,
		file_type="file",
		file_name=content.get("file_name"),
		mime_type=content.get("mime_type"),
		feishu_file_key=content.get("file_key"),
		size_bytes=content.get("file_size"),
		status="stored",
	)
	await _task_queue.add_attachment(attachment)
	await _feishu_bot.reply_text(
		message_id,
		f"📎 已记录文件附件：{attachment.file_name or attachment.id[:8]}\n当前版本仅保存附件元数据，后续会用于表格/图片类运营任务。",
	)


# ---------------------------------------------------------------------------
# Special commands (登录, 账号列表, etc.)
# ---------------------------------------------------------------------------

async def _handle_special_command(text: str, user_id: str, chat_id: str, message_id: str) -> bool:
	"""Handle special commands like login, account list, cancel, etc.

	Returns True if the message was handled as a special command.
	"""
	# Login command: "登录 <平台> <账号名>" or compact natural language variants.
	if text.startswith("登录"):
		parsed_login = _parse_login_command(text)
		if parsed_login is None:
			await _feishu_bot.reply_text(message_id, "格式：登录 <平台> <账号名>\n例如：登录 美团 朝阳店")
			return True

		platform, account_name = parsed_login

		# Create or find account
		accounts = await _account_manager.search_accounts(account_name)
		accounts = [a for a in accounts if a.platform == platform]

		if accounts:
			account = accounts[0]
			await _account_manager.update_status(account.id, AccountStatus.NEEDS_LOGIN)
		else:
			account = await _account_manager.create_account(
				name=account_name,
				platform=platform,
			)

		# Start headful login flow
		await _feishu_bot.reply_text(
			message_id,
			f"🔐 正在打开浏览器登录 {platform}/{account.name}...\n"
			f"请在弹出的浏览器窗口中完成登录操作。",
		)

		# Launch login in background
		asyncio.create_task(_run_login_flow(account.id, chat_id))

		return True

	# Account list command
	if text in ("账号列表", "账号", "账号管理", "accounts"):
		accounts = await _account_manager.get_all_accounts()
		card = _feishu_bot.build_account_card(accounts)
		await _feishu_bot.reply_card(message_id, card)
		return True

	# Help command
	if text in ("帮助", "help", "?", "？"):
		await _feishu_bot.reply_card(message_id, _feishu_bot.build_help_card())
		return True

	if text in ("附件", "最近附件", "uploads", "files"):
		await _show_recent_attachments(user_id, chat_id, message_id)
		return True

	# Cancel command: "取消 <task_id>" or "取消" (cancel all running)
	if text.startswith("取消"):
		parts = text.split(maxsplit=1)

		if len(parts) >= 2:
			# Cancel specific task by ID prefix
			task_id_prefix = parts[1].strip()
			await _cancel_task_by_prefix(task_id_prefix, message_id)
		else:
			# Cancel all running tasks
			await _cancel_all_running(message_id)

		return True

	# Running tasks command
	if text in ("运行中", "任务", "tasks", "状态"):
		await _show_running_tasks(message_id)
		return True

	# History command
	if text in ("历史", "记录", "history"):
		await _show_task_history(message_id)
		return True

	if text in ("指标", "统计", "metrics"):
		await _show_task_metrics(message_id)
		return True

	if text.startswith(("详情", "detail")):
		parts = text.split(maxsplit=1)
		if len(parts) < 2:
			await _feishu_bot.reply_text(message_id, "格式：详情 <任务ID>")
			return True
		await _show_task_detail(parts[1].strip(), message_id)
		return True

	if text.startswith(("日志", "log")):
		parts = text.split(maxsplit=1)
		if len(parts) < 2:
			await _feishu_bot.reply_text(message_id, "格式：日志 <任务ID>")
			return True
		await _show_task_log(parts[1].strip(), message_id)
		return True

	return False


def _parse_login_command(text: str) -> tuple[str, str] | None:
	"""Parse login commands with or without spaces.

	Accepted examples:
	- 登录 美团 朝阳店
	- 登录美团朝阳店
	- 登录美团商家后台朝阳店
	"""
	if not text.startswith("登录"):
		return None

	rest = text.removeprefix("登录").strip()
	if not rest:
		return None

	parts = rest.split(maxsplit=1)
	if len(parts) == 2:
		platform = _resolve_platform(parts[0])
		if platform != "general" and parts[1].strip():
			return platform, parts[1].strip()

	compact = re.sub(r"\s+", "", rest)
	platform_keywords = sorted(
		[*PLATFORM_ALIASES.keys(), "meituan", "douyin", "taobao"],
		key=len,
		reverse=True,
	)

	for keyword in platform_keywords:
		if not compact.lower().startswith(keyword.lower()):
			continue

		platform = _resolve_platform(keyword)
		account_name = compact[len(keyword):].strip()
		for prefix in ("商家后台", "商家中心", "后台", "商家", "店铺", "账号"):
			if account_name.startswith(prefix):
				account_name = account_name[len(prefix):].strip()
				break

		if account_name:
			return platform, account_name

	return None


async def _cancel_task_by_prefix(task_id_prefix: str, message_id: str) -> None:
	"""Cancel a task by its ID prefix (first 8 chars)."""
	# Search in running tasks first
	for task_id in _pool.get_running_task_ids():
		if task_id.startswith(task_id_prefix):
			# Update DB status
			await _task_queue.cancel(task_id)
			# Cancel the running asyncio task + signal cancel event
			cancelled = await _pool.cancel(task_id)
			if cancelled:
				await _feishu_bot.reply_text(message_id, f"🛑 任务 {task_id[:8]} 已取消")
			else:
				await _feishu_bot.reply_text(message_id, f"⚠️ 任务 {task_id[:8]} 无法取消（可能已完成）")
			return

	# Not found in running tasks — check DB
	task = await _task_queue.get_task(task_id_prefix)
	if task:
		if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
			await _feishu_bot.reply_text(message_id, f"任务 {task_id_prefix[:8]} 已经是终态 ({task.status.value})")
		else:
			await _task_queue.cancel(task.id)
			await _feishu_bot.reply_text(message_id, f"🛑 任务 {task_id_prefix[:8]} 已取消")
	else:
		await _feishu_bot.reply_text(message_id, f"❌ 找不到任务 {task_id_prefix}")


async def _cancel_all_running(message_id: str) -> None:
	"""Cancel all currently running tasks."""
	running_ids = _pool.get_running_task_ids()
	if not running_ids:
		await _feishu_bot.reply_text(message_id, "当前没有运行中的任务")
		return

	cancelled_count = 0
	for task_id in running_ids:
		await _task_queue.cancel(task_id)
		if await _pool.cancel(task_id):
			cancelled_count += 1

	await _feishu_bot.reply_text(message_id, f"🛑 已取消 {cancelled_count} 个运行中的任务")


async def _show_running_tasks(message_id: str) -> None:
	"""Show currently running and pending tasks."""
	running_ids = _pool.get_running_task_ids()

	# Also get pending tasks from DB
	pending_tasks = await _task_queue.get_pending_tasks()

	if not running_ids and not pending_tasks:
		await _feishu_bot.reply_text(message_id, "📭 当前没有运行中或等待中的任务")
		return

	lines = ["📊 任务状态："]

	if running_ids:
		lines.append(f"\n🔄 运行中 ({len(running_ids)})：")
		for task_id in running_ids:
			task = await _task_queue.get_task(task_id)
			if task:
				account_info = ""
				if task.account_id:
					account = await _account_manager.get_account(task.account_id)
					if account:
						account_info = f" [{account.name}]"
				lines.append(f"  • {task.id[:8]}{account_info} - {task.instruction[:30]}")

	# Show pending (not yet running)
	pending_only = [t for t in pending_tasks if t.id not in running_ids]
	if pending_only:
		lines.append(f"\n⏳ 等待中 ({len(pending_only)})：")
		for task in pending_only[:5]:  # Show at most 5
			lines.append(f"  • {task.id[:8]} - {task.instruction[:30]}")
		if len(pending_only) > 5:
			lines.append(f"  ... 还有 {len(pending_only) - 5} 个")

	await _feishu_bot.reply_text(message_id, "\n".join(lines))


async def _show_task_history(message_id: str) -> None:
	"""Show recent completed/failed tasks."""
	import aiosqlite

	try:
		db = await aiosqlite.connect(_config.TASK_DB_PATH)
		db.row_factory = aiosqlite.Row
		async with db.execute(
			"SELECT id, platform, instruction, status, account_id, created_at, error "
			"FROM tasks WHERE status IN ('completed', 'failed', 'cancelled') "
			"ORDER BY created_at DESC LIMIT 10"
		) as cursor:
			rows = await cursor.fetchall()
		await db.close()

		if not rows:
			await _feishu_bot.reply_text(message_id, "📭 暂无任务记录")
			return

		lines = ["📋 最近任务记录：\n"]
		for row in rows:
			status_icon = {"completed": "✅", "failed": "❌", "cancelled": "🛑"}.get(row["status"], "❓")
			account_info = ""
			if row["account_id"]:
				account = await _account_manager.get_account(row["account_id"])
				if account:
					account_info = f" [{account.name}]"

			time_str = row["created_at"][:16] if row["created_at"] else ""
			error_info = f" - {row['error'][:30]}" if row["error"] and row["status"] == "failed" else ""

			lines.append(f"{status_icon} {row['id'][:8]}{account_info} | {row['platform']} | {row['instruction'][:25]}{error_info}")
			lines.append(f"   {time_str}\n")

		await _feishu_bot.reply_text(message_id, "\n".join(lines))

	except Exception:
		logger.exception("Failed to show task history")
		await _feishu_bot.reply_text(message_id, "❌ 获取历史记录失败")


async def _show_task_metrics(message_id: str) -> None:
	"""Show aggregate task metrics."""
	try:
		metrics = await _task_queue.get_metrics()
		card = _feishu_bot.build_metrics_card(metrics)
		await _feishu_bot.reply_card(message_id, card)
	except Exception:
		logger.exception("Failed to show task metrics")
		await _feishu_bot.reply_text(message_id, "❌ 获取任务指标失败")


async def _show_recent_attachments(user_id: str, chat_id: str, message_id: str) -> None:
	"""Show recently uploaded attachments for the current chat/user."""
	try:
		attachments = await _task_queue.get_recent_attachments(chat_id=chat_id, user_id=user_id)
		card = _feishu_bot.build_attachment_card(attachments)
		await _feishu_bot.reply_card(message_id, card)
	except Exception:
		logger.exception("Failed to show recent attachments")
		await _feishu_bot.reply_text(message_id, "❌ 获取最近附件失败")


async def _show_task_detail(task_id_prefix: str, message_id: str) -> None:
	"""Show a task detail card by id or id prefix."""
	try:
		task = await _task_queue.get_task_by_prefix(task_id_prefix)
		if not task:
			await _feishu_bot.reply_text(message_id, f"❌ 找不到任务 {task_id_prefix}")
			return
		card = _feishu_bot.build_task_card(task)
		await _feishu_bot.reply_card(message_id, card)
	except Exception:
		logger.exception("Failed to show task detail for %s", task_id_prefix)
		await _feishu_bot.reply_text(message_id, "❌ 获取任务详情失败")


async def _show_task_log(task_id_prefix: str, message_id: str) -> None:
	"""Show a task event timeline by id or id prefix."""
	try:
		task = await _task_queue.get_task_by_prefix(task_id_prefix)
		if not task:
			await _feishu_bot.reply_text(message_id, f"❌ 找不到任务 {task_id_prefix}")
			return

		events = await _task_queue.get_events(task.id)
		if not events:
			await _feishu_bot.reply_text(message_id, f"📭 任务 {task.id[:8]} 暂无日志")
			return

		lines = [f"🧾 任务日志 {task.id[:8]}"]
		for event in events:
			time_str = event.created_at.strftime("%H:%M:%S")
			lines.append(f"{time_str} [{event.event_type}] {event.message}")
		await _feishu_bot.reply_text(message_id, "\n".join(lines))
	except Exception:
		logger.exception("Failed to show task log for %s", task_id_prefix)
		await _feishu_bot.reply_text(message_id, "❌ 获取任务日志失败")


# ---------------------------------------------------------------------------
# Login flow (headful)
# ---------------------------------------------------------------------------

async def _run_login_flow(account_id: str, chat_id: str) -> None:
	"""Run a headful browser login flow for an account."""
	from browser_use import Agent, BrowserSession
	from browser_use.browser.profile import BrowserProfile
	from feishu_browser_use.platforms import get_adapter

	account = await _account_manager.get_account(account_id)
	if not account:
		await _notify(chat_id, "❌ 账号不存在")
		return

	adapter = get_adapter(account.platform)

	login_prompt = f"""你正在帮助用户登录 {adapter.PLATFORM_NAME} 商家后台。

请执行以下步骤：
1. 打开 {adapter.LOGIN_URL}
2. 等待页面加载完成
3. 如果看到登录界面，停下来报告"需要用户手动登录"
4. 如果已登录，报告"登录成功"

不要尝试自动输入用户名密码。只需要打开页面并报告状态。
"""

	try:
		profile = BrowserProfile(
			headless=False,  # headful mode for manual login
			user_data_dir=account.profile_dir,
		)
		session = BrowserSession(browser_profile=profile)
		llm = _create_llm()

		agent = Agent(task=login_prompt, llm=llm, browser_session=session)
		result = await agent.run()

		# Check if login succeeded
		result_str = str(result).lower()
		if "登录成功" in result_str or "已登录" in result_str:
			await _account_manager.update_status(account_id, AccountStatus.ACTIVE)
			await _notify(chat_id, f"✅ {account.name} 登录成功！")
		else:
			await _notify(
				chat_id,
				f"⚠️ {account.name} 登录可能未完成，请检查浏览器窗口。\n"
				f"完成后请重新发送任务。",
			)

		await session.close()

	except Exception as e:
		logger.exception("Login flow failed for account %s", account_id)
		await _notify(chat_id, f"❌ 登录流程异常: {e}")


# ---------------------------------------------------------------------------
# Message parsing with account resolution
# ---------------------------------------------------------------------------

async def _parse_message_with_account(text: str, user_id: str) -> tuple[str, str, object | None]:
	"""Parse a message into platform, instruction, and optional account.

	Supports formats:
	- "朝阳店 美团 搜索咖啡"
	- "美团 朝阳店 搜索咖啡"
	- "搜索咖啡" (no account, no platform)

	Matching priority:
	1. Exact name match
	2. Name starts with keyword
	3. Name contains keyword
	4. Most recently used (tiebreaker)

	Returns:
		(platform, instruction, account_or_None)
	"""
	from feishu_browser_use.account.models import Account

	known_platforms_zh = {
		"美团": "meituan", "外卖": "meituan",
		"抖音": "douyin", "抖店": "douyin",
		"淘宝": "taobao", "千牛": "taobao",
	}
	known_platforms_en = {"meituan", "douyin", "taobao"}

	# Try to find platform keyword
	platform: str | None = None
	remaining = text

	for zh, en in known_platforms_zh.items():
		if zh in text:
			platform = en
			remaining = text.replace(zh, "").strip()
			break

	if not platform:
		for en in known_platforms_en:
			if en in text.lower():
				platform = en
				remaining = text.lower().replace(en, "").strip()
				break

	# Try to find account name in remaining text
	account = None
	if platform and remaining:
		# Split remaining into potential account name and instruction
		parts = remaining.split(maxsplit=1)
		if len(parts) >= 2:
			candidate_name = parts[0]
			instruction = parts[1]

			# Search for matching account
			account = await _resolve_account(candidate_name, platform)
			if account:
				return platform, instruction, account

		account = await _resolve_account_in_text(remaining, platform)
		if account:
			instruction = _remove_account_name_from_instruction(remaining, account.name)
			return platform, instruction or "打开", account

	# No account found, return platform + full text as instruction
	if platform:
		return platform, remaining if remaining else text, None

	return "general", text, None


async def _resolve_account(keyword: str, platform: str) -> object | None:
	"""Resolve an account from a keyword with smart ranking.

	Priority:
	1. Exact name match (case-insensitive)
	2. Name starts with keyword
	3. Name contains keyword
	4. Most recently used (tiebreaker among equals)

	Returns the best matching Account or None.
	"""
	candidates = await _account_manager.find_account_for_message(keyword, platform)
	if not candidates:
		return None
	if len(candidates) == 1:
		return candidates[0]

	# Score and rank
	def _score(account) -> tuple[int, datetime]:
		name_lower = account.name.lower()
		kw_lower = keyword.lower()
		if name_lower == kw_lower:
			return (3, account.last_used_at or account.created_at)
		if name_lower.startswith(kw_lower):
			return (2, account.last_used_at or account.created_at)
		return (1, account.last_used_at or account.created_at)

	candidates.sort(key=_score, reverse=True)
	return candidates[0]


async def _resolve_account_in_text(text: str, platform: str) -> object | None:
	"""Resolve an account whose name appears anywhere in the message text."""
	accounts = await _account_manager.get_accounts_by_platform(platform)
	if not accounts:
		return None

	normalized_text = re.sub(r"\s+", "", text).lower()
	matches = [
		account for account in accounts
		if re.sub(r"\s+", "", account.name).lower() in normalized_text
	]
	if not matches:
		return None

	matches.sort(
		key=lambda account: (
			len(re.sub(r"\s+", "", account.name)),
			account.last_used_at or account.created_at,
		),
		reverse=True,
	)
	return matches[0]


def _remove_account_name_from_instruction(text: str, account_name: str) -> str:
	"""Remove an account name from text while keeping the user's command words."""
	instruction = text.replace(account_name, "", 1).strip()
	return re.sub(r"\s+", " ", instruction).strip()


# ---------------------------------------------------------------------------
# Background worker loop
# ---------------------------------------------------------------------------

async def _worker_loop() -> None:
	"""Background loop that reads tasks from the queue and submits to pool."""
	while True:
		try:
			task = await _task_queue.process_next(timeout=5.0)
			if task is None:
				continue

			logger.info("Worker picked up task %s", task.id)
			await _pool.submit(task)

		except asyncio.CancelledError:
			break
		except Exception:
			logger.exception("Worker loop error")
			await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLATFORM_KEYWORDS = {
	"meituan": {"美团", "meituan"},
	"douyin": {"抖音", "douyin", "抖店"},
	"taobao": {"淘宝", "taobao", "千牛"},
}

PLATFORM_ALIASES = {
	"美团": "meituan",
	"外卖": "meituan",
	"抖音": "douyin",
	"抖店": "douyin",
	"淘宝": "taobao",
	"千牛": "taobao",
}


def _resolve_platform(keyword: str) -> str:
	"""Resolve a platform keyword (Chinese or English) to canonical name."""
	if keyword.lower() in {"meituan", "douyin", "taobao"}:
		return keyword.lower()
	return PLATFORM_ALIASES.get(keyword, "general")


def _create_llm():
	"""Create a ChatOpenAI instance from current config."""
	config = get_config()
	from browser_use.llm.openai.chat import ChatOpenAI
	return ChatOpenAI(
		model=config.LLM_MODEL,
		base_url=config.LLM_BASE_URL,
		api_key=config.LLM_API_KEY,
	)


async def _notify(chat_id: str, text: str) -> None:
	"""Send a notification to a Feishu chat, swallowing errors."""
	try:
		await _feishu_bot.send_text(chat_id, text)
	except Exception:
		logger.warning("Failed to send notification to %s", chat_id, exc_info=True)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
	import uvicorn

	port = int(os.environ.get("PORT", get_config().SERVER_PORT))
	uvicorn.run("feishu_browser_use.server:app", host="0.0.0.0", port=port, reload=False)
