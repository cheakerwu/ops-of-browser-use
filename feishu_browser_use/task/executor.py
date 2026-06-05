"""Task executor with evidence screenshots.

Flow:
1. Agent navigates, fills forms, does work
2. Agent takes screenshot before final submit (evidence)
3. Agent submits
4. Screenshot evidence sent to Feishu user on completion
"""

from __future__ import annotations

import asyncio
import base64
import logging
import tempfile
from pathlib import Path

from browser_use import Agent, BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.llm.openai.chat import ChatOpenAI

from feishu_browser_use.account.manager import AccountManager
from feishu_browser_use.account.models import AccountStatus
from feishu_browser_use.config import Settings
from feishu_browser_use.feishu.bot import FeishuBot
from feishu_browser_use.prompting import PromptRegistry
from feishu_browser_use.platforms import PlatformAdapter, get_adapter
from feishu_browser_use.task.models import Task, TaskResult, TaskStatus
from feishu_browser_use.task.queue import TaskQueue

logger = logging.getLogger(__name__)


class TaskExecutor:
	"""Executes browser automation tasks using browser-use Agent.

	Flow: navigate → do work → screenshot (evidence) → submit → notify with evidence.
	"""

	def __init__(
		self,
		config: Settings,
		queue: TaskQueue,
		feishu_bot: FeishuBot,
		account_manager: AccountManager,
	) -> None:
		self._config = config
		self._queue = queue
		self._feishu_bot = feishu_bot
		self._account_manager = account_manager

	async def execute(self, task: Task, cancel_event: asyncio.Event | None = None) -> TaskResult:
		"""Execute a browser automation task with evidence screenshots.

		Args:
			task: The task to execute.
			cancel_event: Optional event that, when set, signals the task to cancel.

		Returns:
			TaskResult with success/failure details and screenshot paths.
		"""
		platform = task.platform
		adapter = get_adapter(platform)

		# Resolve account and profile directory
		profile_dir: str | None = None
		if task.account_id:
			account = await self._account_manager.get_account(task.account_id)
			if account:
				profile_dir = account.profile_dir
				await self._account_manager.touch(account.id)

		# Create a single browser session for the entire task lifecycle
		browser_session = await self._create_browser_session(profile_dir)

		# Collect screenshots as evidence
		evidence_screenshots: list[str] = []

		try:
			# Check cancel before starting
			if cancel_event and cancel_event.is_set():
				return await self._handle_cancel(task, browser_session)

			# Execute the task
			await self._notify(task.chat_id, f"🔄 任务 {task.id[:8]} 开始执行...")
			await self._set_status(task, TaskStatus.EXECUTING)

			result = await self._run_task(
				task=task,
				adapter=adapter,
				browser_session=browser_session,
				cancel_event=cancel_event,
				evidence_screenshots=evidence_screenshots,
			)

			# Check cancel after execution
			if cancel_event and cancel_event.is_set():
				return await self._handle_cancel(task, browser_session)

			if not result.success:
				await self._handle_failure(task, result)
				return result

			# Check if login is required
			if result.details.get("needs_login"):
				await self._handle_login_required(task, profile_dir)
				return TaskResult(
					success=False,
					message="登录态失效，已通知用户重新登录",
					details={"needs_login": True},
				)

			# Task completed — send evidence screenshots
			await self._set_status(task, TaskStatus.COMPLETED, result=result)
			await self._send_evidence(task, evidence_screenshots)

			return result

		except asyncio.CancelledError:
			return await self._handle_cancel(task, browser_session)

		finally:
			# Always close browser at the end
			if browser_session:
				try:
					await browser_session.close()
				except Exception:
					pass

			# Always clean up screenshot temp files
			for path in evidence_screenshots:
				try:
					Path(path).unlink(missing_ok=True)
				except Exception:
					pass

	async def _run_task(
		self,
		task: Task,
		adapter: PlatformAdapter,
		browser_session: BrowserSession,
		cancel_event: asyncio.Event | None,
		evidence_screenshots: list[str],
	) -> TaskResult:
		"""Run the full task with evidence screenshot capture."""
		try:
			# Check cancel
			if cancel_event and cancel_event.is_set():
				raise asyncio.CancelledError()

			# Build task prompt from structured, policy-checked task fields.
			task.prompt_version = PromptRegistry.VERSION
			task_prompt = PromptRegistry().build(task, phase="execute")

			# Create LLM instance
			llm = ChatOpenAI(
				model=self._config.LLM_MODEL,
				base_url=self._config.LLM_BASE_URL,
				api_key=self._config.LLM_API_KEY,
			)

			# Track the last screenshot for evidence
			last_screenshot_path: str | None = None

			async def _on_step_end(agent: Agent) -> None:
				"""Take a screenshot after each step as potential evidence."""
				nonlocal last_screenshot_path
				try:
					screenshot_bytes = await browser_session.take_screenshot()
					# Save to temp file
					tmp = tempfile.NamedTemporaryFile(
						suffix=".png", delete=False, prefix="evidence_"
					)
					tmp.write(screenshot_bytes)
					tmp.close()
					last_screenshot_path = tmp.name
					evidence_screenshots.append(tmp.name)
					logger.info("Evidence screenshot saved: %s", tmp.name)
				except Exception:
					logger.warning("Failed to take evidence screenshot", exc_info=True)

			# Create agent with existing browser session
			agent = Agent(
				task=task_prompt,
				llm=llm,
				browser_session=browser_session,
			)

			# Execute with step callback for screenshots
			agent_result = await agent.run(
				on_step_end=_on_step_end,
			)

			# Take a final screenshot if we didn't get one from steps
			if not evidence_screenshots:
				try:
					screenshot_bytes = await browser_session.take_screenshot()
					tmp = tempfile.NamedTemporaryFile(
						suffix=".png", delete=False, prefix="evidence_"
					)
					tmp.write(screenshot_bytes)
					tmp.close()
					evidence_screenshots.append(tmp.name)
				except Exception:
					pass

			# Check for login detection in the result
			needs_login = self._detect_login_required(agent_result)

			return TaskResult(
				success=True,
				message="任务执行完成",
				details={"needs_login": needs_login},
			)

		except asyncio.CancelledError:
			raise

		except Exception as e:
			logger.exception("Task %s failed", task.id)
			return TaskResult(success=False, message=f"执行失败: {self._user_friendly_error(e)}")

	def _detect_login_required(self, agent_result: object) -> bool:
		"""Detect from agent result if login is required."""
		if agent_result is None:
			return False

		result_str = str(agent_result).lower()
		login_indicators = [
			"需要重新登录",
			"需要用户手动登录",
			"登录态失效",
			"停留在登录页",
			"当前是登录页",
			"当前显示登录",
			"无法继续",
			"blocked on authentication",
			"authentication required",
			"requires login",
			"login required",
			"sign in required",
			"please sign in",
			"please login",
		]

		for indicator in login_indicators:
			if indicator in result_str:
				return True

		return False

	def _user_friendly_error(self, error: Exception) -> str:
		"""Convert technical exceptions to user-friendly Chinese messages."""
		error_str = str(error).lower()
		error_type = type(error).__name__

		if "timeout" in error_str or error_type == "TimeoutError":
			return "页面加载超时，请稍后重试"
		if "navigation" in error_str and "timeout" in error_str:
			return "页面导航超时，请检查网络或稍后重试"
		if "login" in error_str or "登录" in error_str:
			return "登录态失效，请重新登录后再试"
		if "element" in error_str and "not found" in error_str:
			return "页面元素未找到，可能页面结构已变化"
		if "network" in error_str or "connection" in error_str:
			return "网络连接异常，请检查网络后重试"
		if "permission" in error_str or "forbidden" in error_str:
			return "权限不足，请检查账号权限"

		# Generic fallback
		return str(error)[:100]

	async def _handle_failure(self, task: Task, result: TaskResult) -> None:
		"""Handle task failure: update status and notify user."""
		await self._set_status(
			task,
			TaskStatus.FAILED,
			error=result.message,
			error_type="execution_failed",
			error_message_user=result.message,
			error_message_internal=result.message,
		)
		await self._notify(task.chat_id, f"❌ 任务 {task.id[:8]} 失败: {result.message}")

	async def _handle_cancel(self, task: Task, browser_session: BrowserSession | None) -> TaskResult:
		"""Handle task cancellation: update status, close browser, notify user."""
		await self._set_status(
			task,
			TaskStatus.CANCELLED,
			error="用户取消",
			error_type="user_cancelled",
			error_message_user="用户取消",
			error_message_internal="用户取消",
		)
		await self._notify(task.chat_id, f"🛑 任务 {task.id[:8]} 已取消")
		return TaskResult(success=False, message="用户取消")

	async def _handle_login_required(self, task: Task, profile_dir: str | None) -> None:
		"""Handle login required: update account status and notify user."""
		if task.account_id:
			await self._account_manager.update_status(task.account_id, AccountStatus.NEEDS_LOGIN)

		await self._set_status(
			task,
			TaskStatus.FAILED,
			error="登录态失效，需要重新登录",
			error_type="needs_login",
			error_message_user="登录态失效，需要重新登录",
			error_message_internal="登录态失效，需要重新登录",
		)

		await self._notify(
			task.chat_id,
			f"⚠️ 任务 {task.id[:8]} 需要重新登录\n"
			f"请发送 \"登录 {task.platform} <账号名>\" 重新登录后重试",
		)

	async def _set_status(self, task: Task, status: TaskStatus, **kwargs) -> None:
		"""Persist task status and refresh its Feishu task card when possible."""
		await self._queue.update_status(task.id, status, **kwargs)
		task.status = status
		for key, value in kwargs.items():
			if hasattr(task, key):
				setattr(task, key, value)
		try:
			await self._feishu_bot.update_task_card(task)
		except Exception:
			logger.warning("Failed to update task card for %s", task.id, exc_info=True)

	async def _send_evidence(self, task: Task, screenshot_paths: list[str]) -> None:
		"""Send evidence screenshots to the Feishu user."""
		if not screenshot_paths:
			await self._notify(task.chat_id, f"✅ 任务 {task.id[:8]} 执行成功！（无截图证据）")
			return

		# Send the last screenshot as the primary evidence
		# (it shows the final state before submit)
		last_screenshot = screenshot_paths[-1]

		try:
			# Upload image to Feishu and get image_key
			image_key = await self._feishu_bot.upload_image(last_screenshot)
			if image_key:
				await self._queue.add_event(
					task.id,
					"evidence_uploaded",
					"截图证据已上传",
					{"image_key": image_key},
				)
				await self._feishu_bot.send_image(task.chat_id, image_key)
				await self._notify(
					task.chat_id,
					f"✅ 任务 {task.id[:8]} 执行成功！\n📸 以上为执行截图证据",
				)
			else:
				await self._queue.add_event(
					task.id,
					"evidence_upload_failed",
					"截图上传失败",
					{"path": last_screenshot},
				)
				await self._notify(task.chat_id, f"✅ 任务 {task.id[:8]} 执行成功！（截图上传失败）")
		except Exception:
			logger.warning("Failed to send evidence screenshot", exc_info=True)
			await self._queue.add_event(
				task.id,
				"evidence_send_failed",
				"截图发送失败",
				{"path": last_screenshot},
			)
			await self._notify(task.chat_id, f"✅ 任务 {task.id[:8]} 执行成功！（截图发送失败）")

	async def _notify(self, chat_id: str, text: str) -> None:
		"""Send a notification to a Feishu chat, swallowing errors."""
		try:
			await self._feishu_bot.send_text(chat_id, text)
		except Exception:
			logger.warning("Failed to send notification to %s", chat_id, exc_info=True)

	async def _create_browser_session(self, profile_dir: str | None) -> BrowserSession:
		"""Create a BrowserSession with the given profile directory."""
		profile_kwargs: dict = {
			"headless": self._config.BROWSER_HEADLESS,
		}

		if profile_dir:
			profile_kwargs["user_data_dir"] = profile_dir
		elif self._config.BROWSER_USER_DATA_DIR:
			profile_kwargs["user_data_dir"] = self._config.BROWSER_USER_DATA_DIR

		profile = BrowserProfile(**profile_kwargs)
		return BrowserSession(browser_profile=profile)
