from datetime import datetime, timedelta

import pytest

from feishu_browser_use.task.models import Task, TaskStatus
from feishu_browser_use.task.queue import TaskQueue


@pytest.mark.asyncio
async def test_task_queue_metrics_summary(tmp_path):
	db_path = tmp_path / "tasks.db"
	queue = TaskQueue(str(db_path))
	await queue.start()
	base = datetime(2026, 1, 1, 10, 0)

	completed = Task(
		user_id="u1",
		chat_id="c",
		platform="meituan",
		instruction="打开",
		intent="open_merchant_backend",
		status=TaskStatus.COMPLETED,
		created_at=base,
		updated_at=base + timedelta(seconds=20),
	)
	failed = Task(
		user_id="u2",
		chat_id="c",
		platform="douyin",
		instruction="打开",
		intent="open_merchant_backend",
		status=TaskStatus.FAILED,
		error_type="needs_login",
		created_at=base,
		updated_at=base + timedelta(seconds=40),
	)
	pending = Task(
		user_id="u3",
		chat_id="c",
		platform="meituan",
		instruction="打开",
		intent="open_merchant_backend",
		status=TaskStatus.PENDING,
		created_at=base,
		updated_at=base,
	)

	await queue.submit(completed)
	await queue.submit(failed)
	await queue.submit(pending)

	metrics = await queue.get_metrics()
	await queue.close()

	assert metrics.total_tasks == 3
	assert metrics.terminal_tasks == 2
	assert metrics.completed_tasks == 1
	assert metrics.failed_tasks == 1
	assert metrics.success_rate == 0.5
	assert metrics.failure_rate == 0.5
	assert metrics.average_duration_seconds == 30
	assert metrics.by_platform["meituan"].total == 2
	assert metrics.by_platform["meituan"].completed == 1
	assert metrics.by_platform["douyin"].failed == 1
	assert metrics.by_intent["open_merchant_backend"].total == 3
	assert metrics.error_types == {"needs_login": 1}
