from datetime import datetime
from types import SimpleNamespace

import pytest

import feishu_browser_use.server as server
from feishu_browser_use.task.models import Task, TaskEvent, TaskStatus


class FakeTaskQueue:
	def __init__(self, task, events):
		self.task = task
		self.events = events

	async def get_task(self, task_id):
		if self.task.id.startswith(task_id):
			return self.task
		return None

	async def get_events(self, task_id):
		return self.events


class FakeBot:
	def __init__(self):
		self.cards = []
		self.texts = []

	async def reply_card(self, message_id, card):
		self.cards.append((message_id, card))

	async def reply_text(self, message_id, text):
		self.texts.append((message_id, text))

	def build_task_card(self, task):
		return {"task": task.id, "status": task.status.value}


@pytest.mark.asyncio
async def test_detail_command_replies_with_task_detail_card(monkeypatch):
	task = Task(
		id="06aabcdef123",
		user_id="u",
		chat_id="c",
		platform="meituan",
		instruction="打开",
		status=TaskStatus.COMPLETED,
		raw_text="打开美团江湖饭焗",
	)
	bot = FakeBot()
	monkeypatch.setattr(server, "_task_queue", FakeTaskQueue(task, []))
	monkeypatch.setattr(server, "_feishu_bot", bot)

	handled = await server._handle_special_command("详情 06aabc", "u", "c", "msg")

	assert handled is True
	assert bot.cards == [("msg", {"task": "06aabcdef123", "status": "completed"})]


@pytest.mark.asyncio
async def test_log_command_replies_with_task_events(monkeypatch):
	task = Task(
		id="06aabcdef123",
		user_id="u",
		chat_id="c",
		platform="meituan",
		instruction="打开",
	)
	events = [
		TaskEvent(task_id=task.id, event_type="created", message="任务已创建", created_at=datetime(2026, 1, 1, 10, 0)),
		TaskEvent(task_id=task.id, event_type="completed", message="任务执行成功", created_at=datetime(2026, 1, 1, 10, 1)),
	]
	bot = FakeBot()
	monkeypatch.setattr(server, "_task_queue", FakeTaskQueue(task, events))
	monkeypatch.setattr(server, "_feishu_bot", bot)

	handled = await server._handle_special_command("日志 06aabc", "u", "c", "msg")

	assert handled is True
	assert "任务已创建" in bot.texts[0][1]
	assert "任务执行成功" in bot.texts[0][1]
