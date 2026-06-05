import json
from types import SimpleNamespace

import pytest

import feishu_browser_use.server as server


class FakeTaskQueue:
	def __init__(self):
		self.submitted = []
		self.card_message_ids = []

	async def submit(self, task):
		self.submitted.append(task)
		return task.id

	async def set_task_card_message_id(self, task_id, message_id):
		self.card_message_ids.append((task_id, message_id))


class FakePool:
	def __init__(self):
		self.submitted = []

	async def submit(self, task):
		self.submitted.append(task)


class FakeBot:
	def __init__(self):
		self.replies = []
		self.cards = []

	async def reply_text(self, message_id, content):
		self.replies.append((message_id, content))

	async def reply_card(self, message_id, card):
		self.cards.append((message_id, card))

	def build_task_card(self, task):
		return {"task_id": task.id, "platform": task.platform, "intent": task.intent}

	async def reply_task_card(self, message_id, task):
		self.cards.append((message_id, self.build_task_card(task)))
		return "om_task_card"


@pytest.mark.asyncio
async def test_message_event_enqueues_task_without_direct_pool_submit(monkeypatch):
	queue = FakeTaskQueue()
	pool = FakePool()
	bot = FakeBot()
	account = SimpleNamespace(id="acc-1", name="江湖饭焗")

	monkeypatch.setattr(server, "_task_queue", queue)
	monkeypatch.setattr(server, "_pool", pool)
	monkeypatch.setattr(server, "_feishu_bot", bot)
	monkeypatch.setattr(
		server,
		"_parse_message_with_account",
		lambda text, user_id: _async_result(("meituan", "打开", account)),
	)

	await server._handle_message_event(
		{
			"sender": {"sender_id": {"open_id": "user-1"}},
			"message": {
				"chat_id": "chat-1",
				"message_id": "msg-1",
				"message_type": "text",
				"content": json.dumps({"text": "打开美团江湖饭焗"}),
			},
		}
	)

	assert len(queue.submitted) == 1
	assert pool.submitted == []
	assert queue.submitted[0].account_id == "acc-1"
	assert queue.submitted[0].raw_text == "打开美团江湖饭焗"
	assert queue.submitted[0].policy_status == "allowed"
	assert queue.submitted[0].intent == "open_merchant_backend"
	assert queue.submitted[0].intent_target == "merchant_backend"
	assert queue.submitted[0].intent_params == {}
	assert queue.submitted[0].intent_confidence == 0.95
	assert queue.submitted[0].prompt_version == "merchant-ops-v1"
	assert bot.cards[0][0] == "msg-1"
	assert queue.card_message_ids == [(queue.submitted[0].id, "om_task_card")]


@pytest.mark.asyncio
async def test_message_event_blocks_non_whitelisted_url(monkeypatch):
	queue = FakeTaskQueue()
	pool = FakePool()
	bot = FakeBot()

	monkeypatch.setattr(server, "_task_queue", queue)
	monkeypatch.setattr(server, "_pool", pool)
	monkeypatch.setattr(server, "_feishu_bot", bot)
	monkeypatch.setattr(
		server,
		"_parse_message_with_account",
		lambda text, user_id: _async_result(("general", text, None)),
	)

	await server._handle_message_event(
		{
			"sender": {"sender_id": {"open_id": "user-1"}},
			"message": {
				"chat_id": "chat-1",
				"message_id": "msg-1",
				"message_type": "text",
				"content": json.dumps({"text": "打开 https://example.com"}),
			},
		}
	)

	assert queue.submitted == []
	assert pool.submitted == []
	assert "不支持访问非白名单网站" in bot.replies[0][1]


async def _async_result(value):
	return value
