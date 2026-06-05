import pytest

from feishu_browser_use.task.executor import TaskExecutor
from feishu_browser_use.task.models import Task, TaskStatus


class FakeQueue:
	def __init__(self):
		self.updated = []

	async def update_status(self, task_id, status, **kwargs):
		self.updated.append((task_id, status, kwargs))


class FakeBot:
	def __init__(self):
		self.updated = []
		self.messages = []

	async def update_task_card(self, task):
		self.updated.append((task.id, task.status))

	async def send_text(self, chat_id, text):
		self.messages.append((chat_id, text))


@pytest.mark.asyncio
async def test_executor_updates_task_card_on_failure():
	queue = FakeQueue()
	bot = FakeBot()
	executor = TaskExecutor(
		config=None,
		queue=queue,
		feishu_bot=bot,
		account_manager=None,
	)
	task = Task(
		user_id="u",
		chat_id="c",
		platform="meituan",
		instruction="打开",
		task_card_message_id="om_task_card",
	)

	await executor._set_status(task, TaskStatus.FAILED, error="失败")

	assert task.status == TaskStatus.FAILED
	assert bot.updated == [(task.id, TaskStatus.FAILED)]
	assert queue.updated[0][1] == TaskStatus.FAILED
