import pytest

from feishu_browser_use.feishu.bot import FeishuBot
from feishu_browser_use.task.models import Task
from feishu_browser_use.task.queue import TaskQueue


class FakeResponse:
	def __init__(self, message_id="om_card"):
		self.data = type("Data", (), {"message_id": message_id})()

	def success(self):
		return True


class FakeMessageApi:
	def __init__(self):
		self.reply_request = None
		self.update_request = None

	async def areply(self, request):
		self.reply_request = request
		return FakeResponse("om_replied_card")

	async def aupdate(self, request):
		self.update_request = request
		return FakeResponse("om_updated_card")


class FakeClient:
	def __init__(self):
		self.message_api = FakeMessageApi()
		self.im = type("IM", (), {
			"v1": type("V1", (), {"message": self.message_api})()
		})()


@pytest.mark.asyncio
async def test_task_queue_persists_task_card_message_id(tmp_path):
	db_path = tmp_path / "tasks.db"
	queue = TaskQueue(str(db_path))
	await queue.start()
	task = Task(user_id="u", chat_id="c", platform="meituan", instruction="打开")

	await queue.submit(task)
	await queue.set_task_card_message_id(task.id, "om_card_message")
	loaded = await queue.get_task(task.id)
	await queue.close()

	assert loaded is not None
	assert loaded.task_card_message_id == "om_card_message"


@pytest.mark.asyncio
async def test_reply_task_card_returns_created_message_id():
	client = FakeClient()
	bot = FeishuBot(client)
	task = Task(user_id="u", chat_id="c", platform="meituan", instruction="打开")

	message_id = await bot.reply_task_card("om_source", task)

	assert message_id == "om_replied_card"
	assert client.message_api.reply_request.message_id == "om_source"


@pytest.mark.asyncio
async def test_update_task_card_updates_existing_message():
	client = FakeClient()
	bot = FeishuBot(client)
	task = Task(
		user_id="u",
		chat_id="c",
		platform="meituan",
		instruction="打开",
		task_card_message_id="om_task_card",
	)

	await bot.update_task_card(task)

	request = client.message_api.update_request
	assert request.message_id == "om_task_card"
	assert request.request_body.msg_type == "interactive"
