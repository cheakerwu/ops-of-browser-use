import json

import pytest

import feishu_browser_use.server as server


class FakeTaskQueue:
	def __init__(self):
		self.attachments = []

	async def add_attachment(self, attachment):
		self.attachments.append(attachment)
		return attachment.id


class FakeBot:
	def __init__(self):
		self.replies = []

	async def reply_text(self, message_id, text):
		self.replies.append((message_id, text))


@pytest.mark.asyncio
async def test_image_message_is_stored_as_attachment(monkeypatch):
	queue = FakeTaskQueue()
	bot = FakeBot()
	monkeypatch.setattr(server, "_task_queue", queue)
	monkeypatch.setattr(server, "_feishu_bot", bot)

	await server._handle_message_event(
		{
			"schema": "tenant",
			"sender": {"sender_id": {"open_id": "user-1"}},
			"message": {
				"chat_id": "chat-1",
				"message_id": "msg-1",
				"message_type": "image",
				"content": json.dumps({"image_key": "img_key"}),
			},
		}
	)

	assert len(queue.attachments) == 1
	assert queue.attachments[0].file_type == "image"
	assert queue.attachments[0].feishu_file_key == "img_key"
	assert "已记录图片附件" in bot.replies[0][1]


@pytest.mark.asyncio
async def test_file_message_is_stored_as_attachment(monkeypatch):
	queue = FakeTaskQueue()
	bot = FakeBot()
	monkeypatch.setattr(server, "_task_queue", queue)
	monkeypatch.setattr(server, "_feishu_bot", bot)

	await server._handle_message_event(
		{
			"schema": "tenant",
			"sender": {"sender_id": {"open_id": "user-1"}},
			"message": {
				"chat_id": "chat-1",
				"message_id": "msg-1",
				"message_type": "file",
				"content": json.dumps({
					"file_key": "file_key",
					"file_name": "prices.xlsx",
					"file_size": 2048,
				}),
			},
		}
	)

	assert len(queue.attachments) == 1
	assert queue.attachments[0].file_type == "file"
	assert queue.attachments[0].file_name == "prices.xlsx"
	assert queue.attachments[0].size_bytes == 2048
	assert "已记录文件附件" in bot.replies[0][1]
