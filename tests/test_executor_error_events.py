import pytest

from feishu_browser_use.task.executor import TaskExecutor
from feishu_browser_use.task.models import Task, TaskResult, TaskStatus


class FakeQueue:
	def __init__(self):
		self.updated = []
		self.events = []

	async def update_status(self, task_id, status, **kwargs):
		self.updated.append((task_id, status, kwargs))

	async def add_event(self, task_id, event_type, message, details=None):
		self.events.append((task_id, event_type, message, details or {}))


class FakeBot:
	async def send_text(self, chat_id, text):
		pass


@pytest.mark.asyncio
async def test_handle_failure_stores_readable_error_fields():
	queue = FakeQueue()
	executor = TaskExecutor(
		config=None,
		queue=queue,
		feishu_bot=FakeBot(),
		account_manager=None,
	)
	task = Task(user_id="u", chat_id="c", platform="meituan", instruction="打开")

	await executor._handle_failure(
		task,
		TaskResult(success=False, message="执行失败: LLM call timed out after 75 seconds"),
	)

	assert queue.updated == [
		(
			task.id,
			TaskStatus.FAILED,
			{
				"error": "执行失败: LLM call timed out after 75 seconds",
				"error_type": "execution_failed",
				"error_message_user": "执行失败: LLM call timed out after 75 seconds",
				"error_message_internal": "执行失败: LLM call timed out after 75 seconds",
			},
		)
	]
