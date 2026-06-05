from feishu_browser_use.prompting import PromptRegistry
from feishu_browser_use.task.models import Task


def test_prompt_registry_builds_open_backend_prompt_with_safety_context():
	task = Task(
		user_id="u",
		chat_id="c",
		platform="meituan",
		instruction="打开",
		intent="open_merchant_backend",
		intent_target="merchant_backend",
		intent_params={},
		intent_confidence=0.95,
		allowed_domains=["e.waimai.meituan.com"],
	)

	prompt = PromptRegistry().build(task, phase="execute")

	assert "Prompt版本：merchant-ops-v1" in prompt
	assert "任务意图：open_merchant_backend" in prompt
	assert "允许访问域名：e.waimai.meituan.com" in prompt
	assert "如果跳转到非允许域名，立即停止" in prompt
	assert "打开" in prompt


def test_prompt_registry_uses_change_price_fields():
	task = Task(
		user_id="u",
		chat_id="c",
		platform="meituan",
		instruction="咖啡价格改成25元",
		intent="change_price",
		intent_target="咖啡",
		intent_params={"price": 25.0},
		allowed_domains=["e.waimai.meituan.com"],
	)

	prompt = PromptRegistry().build(task, phase="execute")

	assert "任务意图：change_price" in prompt
	assert "目标对象：咖啡" in prompt
	assert '"price": 25.0' in prompt
