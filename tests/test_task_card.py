from feishu_browser_use.feishu.bot import FeishuBot
from feishu_browser_use.task.models import Task


def test_task_card_shows_audit_and_policy_fields():
	task = Task(
		user_id="u",
		chat_id="c",
		platform="meituan",
		instruction="打开",
		account_id="acc-1",
		intent="open_merchant_backend",
		intent_target="merchant_backend",
		intent_confidence=0.95,
		prompt_version="merchant-ops-v1",
		policy_status="allowed",
		policy_reason="允许执行",
		raw_text="打开美团江湖饭焗",
	)

	card = FeishuBot(client=None).build_task_card(task)
	content = str(card)

	assert "任务" in content
	assert "open_merchant_backend" in content
	assert "merchant_backend" in content
	assert "merchant-ops-v1" in content
	assert "allowed" in content
	assert "打开美团江湖饭焗" in content
	assert "取消" in content
