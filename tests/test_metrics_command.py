import pytest

import feishu_browser_use.server as server
from feishu_browser_use.feishu.bot import FeishuBot
from feishu_browser_use.task.models import TaskMetricBucket, TaskMetrics


class FakeTaskQueue:
	async def get_metrics(self):
		return TaskMetrics(
			total_tasks=4,
			terminal_tasks=3,
			completed_tasks=2,
			failed_tasks=1,
			success_rate=2 / 3,
			failure_rate=1 / 3,
			average_duration_seconds=12.5,
			by_platform={
				"meituan": TaskMetricBucket(total=3, completed=2, failed=1),
			},
			error_types={"needs_login": 1},
		)


class FakeBot:
	def __init__(self):
		self.cards = []

	async def reply_card(self, message_id, card):
		self.cards.append((message_id, card))

	def build_metrics_card(self, metrics):
		return FeishuBot(client=None).build_metrics_card(metrics)


def test_build_metrics_card_contains_core_metrics():
	metrics = TaskMetrics(
		total_tasks=4,
		terminal_tasks=3,
		completed_tasks=2,
		failed_tasks=1,
		success_rate=2 / 3,
		failure_rate=1 / 3,
		average_duration_seconds=12.5,
		by_platform={"meituan": TaskMetricBucket(total=3, completed=2, failed=1)},
		error_types={"needs_login": 1},
	)

	card = FeishuBot(client=None).build_metrics_card(metrics)
	content = str(card)

	assert "任务指标" in content
	assert "66.7%" in content
	assert "needs_login" in content
	assert "美团" in content


@pytest.mark.asyncio
async def test_metrics_command_replies_with_metrics_card(monkeypatch):
	bot = FakeBot()
	monkeypatch.setattr(server, "_task_queue", FakeTaskQueue())
	monkeypatch.setattr(server, "_feishu_bot", bot)

	handled = await server._handle_special_command("指标", "u", "c", "msg")

	assert handled is True
	assert bot.cards[0][0] == "msg"
	assert "任务指标" in str(bot.cards[0][1])
