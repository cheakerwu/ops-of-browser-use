import pytest

from feishu_browser_use.task.executor import TaskExecutor
from feishu_browser_use.task.models import Task


class FakeQueue:
	async def update_status(self, *args, **kwargs):
		pass

	async def add_event(self, *args, **kwargs):
		pass


class FakeBot:
	async def update_task_card(self, task):
		pass

	async def send_text(self, chat_id, text):
		pass


class FakeSession:
	async def take_screenshot(self):
		return b"png"


class FakeAgentResult:
	def __str__(self):
		return "已完成"


@pytest.mark.asyncio
async def test_run_task_uses_prompt_registry(monkeypatch):
	captured = {}

	class FakeAgent:
		def __init__(self, task, llm, browser_session):
			captured["prompt"] = task

		async def run(self, on_step_end=None):
			return FakeAgentResult()

	class FakeChatOpenAI:
		def __init__(self, **kwargs):
			pass

	monkeypatch.setattr("feishu_browser_use.task.executor.Agent", FakeAgent)
	monkeypatch.setattr("feishu_browser_use.task.executor.ChatOpenAI", FakeChatOpenAI)

	executor = TaskExecutor(
		config=type("Config", (), {"LLM_MODEL": "m", "LLM_BASE_URL": "u", "LLM_API_KEY": "k"})(),
		queue=FakeQueue(),
		feishu_bot=FakeBot(),
		account_manager=None,
	)
	task = Task(
		user_id="u",
		chat_id="c",
		platform="meituan",
		instruction="打开",
		intent="open_merchant_backend",
		intent_target="merchant_backend",
		allowed_domains=["e.waimai.meituan.com"],
	)

	result = await executor._run_task(
		task=task,
		adapter=type("Adapter", (), {})(),
		browser_session=FakeSession(),
		cancel_event=None,
		evidence_screenshots=[],
	)

	assert result.success is True
	assert task.prompt_version == "merchant-ops-v1"
	assert "Prompt版本：merchant-ops-v1" in captured["prompt"]
	assert "任务意图：open_merchant_backend" in captured["prompt"]
