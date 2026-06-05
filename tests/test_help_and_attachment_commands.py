from datetime import datetime

import pytest

import feishu_browser_use.server as server
from feishu_browser_use.feishu.bot import FeishuBot
from feishu_browser_use.task.models import Attachment


class FakeTaskQueue:
	def __init__(self, attachments=None):
		self.attachments = attachments or []

	async def get_recent_attachments(self, chat_id: str, user_id: str | None = None, limit: int = 5):
		return self.attachments[:limit]


class FakeBot:
	def __init__(self):
		self.cards = []
		self.texts = []

	async def reply_card(self, message_id, card):
		self.cards.append((message_id, card))

	async def reply_text(self, message_id, text):
		self.texts.append((message_id, text))

	def build_help_card(self):
		return FeishuBot(client=None).build_help_card()

	def build_attachment_card(self, attachments):
		return FeishuBot(client=None).build_attachment_card(attachments)


def test_help_card_contains_supported_commands_and_upload_guidance():
	card = FeishuBot(client=None).build_help_card()
	content = str(card)

	assert "使用指南" in content
	assert "登录 美团 江湖饭焗" in content
	assert "详情 <任务ID>" in content
	assert "图片" in content
	assert "表格" in content


@pytest.mark.asyncio
async def test_help_command_replies_with_help_card(monkeypatch):
	bot = FakeBot()
	monkeypatch.setattr(server, "_feishu_bot", bot)

	handled = await server._handle_special_command("帮助", "u", "c", "msg")

	assert handled is True
	assert bot.cards[0][0] == "msg"
	assert "使用指南" in str(bot.cards[0][1])


def test_attachment_card_lists_recent_uploads():
	attachments = [
		Attachment(
			id="att-image-123",
			file_type="image",
			file_name="门店图",
			created_at=datetime(2026, 1, 1, 10, 0),
		),
		Attachment(
			id="att-file-123",
			file_type="file",
			file_name="价格表.xlsx",
			size_bytes=2048,
			created_at=datetime(2026, 1, 1, 10, 1),
		),
	]

	card = FeishuBot(client=None).build_attachment_card(attachments)
	content = str(card)

	assert "最近附件" in content
	assert "门店图" in content
	assert "价格表.xlsx" in content
	assert "2.0 KB" in content


@pytest.mark.asyncio
async def test_attachment_command_replies_with_recent_attachment_card(monkeypatch):
	attachment = Attachment(
		id="att-file-123",
		file_type="file",
		file_name="价格表.xlsx",
		size_bytes=2048,
	)
	bot = FakeBot()
	monkeypatch.setattr(server, "_task_queue", FakeTaskQueue([attachment]))
	monkeypatch.setattr(server, "_feishu_bot", bot)

	handled = await server._handle_special_command("附件", "u", "c", "msg")

	assert handled is True
	assert bot.cards[0][0] == "msg"
	assert "价格表.xlsx" in str(bot.cards[0][1])
