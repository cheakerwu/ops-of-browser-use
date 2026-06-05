from datetime import datetime

import pytest

from feishu_browser_use.task.models import Attachment, Task
from feishu_browser_use.task.queue import TaskQueue


@pytest.mark.asyncio
async def test_task_queue_persists_attachment_metadata(tmp_path):
	db_path = tmp_path / "tasks.db"
	queue = TaskQueue(str(db_path))
	await queue.start()

	attachment = Attachment(
		tenant_key="tenant",
		chat_id="chat",
		message_id="msg",
		uploaded_by_user_id="user",
		file_type="image",
		file_name="menu.png",
		mime_type="image/png",
		feishu_file_key="img_v2_key",
		size_bytes=123,
		status="stored",
	)
	await queue.add_attachment(attachment)
	loaded = await queue.get_attachment(attachment.id)
	await queue.close()

	assert loaded is not None
	assert loaded.file_type == "image"
	assert loaded.file_name == "menu.png"
	assert loaded.feishu_file_key == "img_v2_key"


@pytest.mark.asyncio
async def test_task_queue_links_attachment_to_task(tmp_path):
	db_path = tmp_path / "tasks.db"
	queue = TaskQueue(str(db_path))
	await queue.start()
	task = Task(user_id="u", chat_id="c", platform="meituan", instruction="上传图片")
	attachment = Attachment(
		chat_id="c",
		message_id="msg",
		uploaded_by_user_id="u",
		file_type="image",
		file_name="store.png",
		feishu_file_key="img_key",
		status="stored",
	)

	await queue.submit(task)
	await queue.add_attachment(attachment)
	await queue.link_attachment(task.id, attachment.id, purpose="input_image")
	attachments = await queue.get_task_attachments(task.id)
	events = await queue.get_events(task.id)
	await queue.close()

	assert [item.id for item in attachments] == [attachment.id]
	assert events[-1].event_type == "attachment_linked"
	assert events[-1].details == {"attachment_id": attachment.id, "purpose": "input_image"}


@pytest.mark.asyncio
async def test_task_queue_returns_recent_attachments_scoped_to_chat_and_user(tmp_path):
	db_path = tmp_path / "tasks.db"
	queue = TaskQueue(str(db_path))
	await queue.start()
	attachments = [
		Attachment(
			id="first",
			chat_id="chat-1",
			uploaded_by_user_id="user-1",
			file_type="image",
			file_name="first.png",
			created_at=datetime(2026, 1, 1, 10, 0),
		),
		Attachment(
			id="second",
			chat_id="chat-1",
			uploaded_by_user_id="user-1",
			file_type="file",
			file_name="second.xlsx",
			created_at=datetime(2026, 1, 1, 10, 1),
		),
		Attachment(
			id="other-user",
			chat_id="chat-1",
			uploaded_by_user_id="user-2",
			file_type="file",
			file_name="other.xlsx",
			created_at=datetime(2026, 1, 1, 10, 2),
		),
		Attachment(
			id="other-chat",
			chat_id="chat-2",
			uploaded_by_user_id="user-1",
			file_type="file",
			file_name="other-chat.xlsx",
			created_at=datetime(2026, 1, 1, 10, 3),
		),
	]
	for attachment in attachments:
		await queue.add_attachment(attachment)

	recent = await queue.get_recent_attachments("chat-1", "user-1")
	await queue.close()

	assert [attachment.id for attachment in recent] == ["second", "first"]
