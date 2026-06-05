import aiosqlite
import pytest

from feishu_browser_use.task.models import Task, TaskStatus
from feishu_browser_use.task.queue import TaskQueue


@pytest.mark.asyncio
async def test_task_queue_persists_audit_fields_and_created_event(tmp_path):
	db_path = tmp_path / "tasks.db"
	queue = TaskQueue(str(db_path))
	await queue.start()

	task = Task(
		user_id="ou_user",
		chat_id="oc_chat",
		message_id="om_message",
		raw_text="打开美团江湖饭焗",
		platform="meituan",
		instruction="打开",
		account_id="account-1",
		intent="open_merchant_backend",
		intent_target="merchant_backend",
		intent_params={"source": "test"},
		intent_confidence=0.95,
		prompt_version="merchant-ops-v1",
		policy_status="allowed",
		policy_reason="允许执行",
		allowed_domains=["e.waimai.meituan.com", "waimaie.meituan.com"],
	)

	await queue.submit(task)
	loaded = await queue.get_task(task.id)
	events = await queue.get_events(task.id)
	await queue.close()

	assert loaded is not None
	assert loaded.message_id == "om_message"
	assert loaded.raw_text == "打开美团江湖饭焗"
	assert loaded.intent == "open_merchant_backend"
	assert loaded.intent_target == "merchant_backend"
	assert loaded.intent_params == {"source": "test"}
	assert loaded.intent_confidence == 0.95
	assert loaded.prompt_version == "merchant-ops-v1"
	assert loaded.allowed_domains == ["e.waimai.meituan.com", "waimaie.meituan.com"]
	assert [(event.event_type, event.message) for event in events] == [
		("created", "任务已创建")
	]


@pytest.mark.asyncio
async def test_task_queue_records_status_events(tmp_path):
	db_path = tmp_path / "tasks.db"
	queue = TaskQueue(str(db_path))
	await queue.start()

	task = Task(
		user_id="ou_user",
		chat_id="oc_chat",
		platform="meituan",
		instruction="打开",
	)
	await queue.submit(task)
	await queue.update_status(
		task.id,
		TaskStatus.FAILED,
		error="页面加载超时",
		error_type="page_timeout",
		error_message_user="页面加载超时，请稍后重试",
	)

	loaded = await queue.get_task(task.id)
	events = await queue.get_events(task.id)
	await queue.close()

	assert loaded is not None
	assert loaded.error_type == "page_timeout"
	assert loaded.error_message_user == "页面加载超时，请稍后重试"
	assert [event.event_type for event in events] == ["created", "failed"]


@pytest.mark.asyncio
async def test_task_queue_creates_attachment_tables(tmp_path):
	db_path = tmp_path / "tasks.db"
	queue = TaskQueue(str(db_path))
	await queue.start()
	await queue.close()

	async with aiosqlite.connect(db_path) as db:
		async with db.execute(
			"SELECT name FROM sqlite_master WHERE type='table' AND name IN ('attachments', 'task_attachments')"
		) as cursor:
			names = {row[0] for row in await cursor.fetchall()}

	assert names == {"attachments", "task_attachments"}
