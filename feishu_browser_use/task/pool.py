"""Concurrent task executor pool with per-account serialization.

Concurrency model:
- Global semaphore limits total concurrent browser instances
- Per-account lock ensures same-account tasks run serially
- Different accounts can run in parallel within the global limit
"""

from __future__ import annotations

import asyncio
import logging

from feishu_browser_use.task.executor import TaskExecutor
from feishu_browser_use.task.models import Task

logger = logging.getLogger(__name__)


class TaskExecutorPool:
	"""Manages concurrent task execution with account-level isolation.

	Usage:
		pool = TaskExecutorPool(executor, max_concurrent=3)
		await pool.submit(task)  # non-blocking, queued internally
	"""

	def __init__(self, executor: TaskExecutor, max_concurrent: int = 3) -> None:
		self._executor = executor
		self._global_semaphore = asyncio.Semaphore(max_concurrent)
		self._account_locks: dict[str, asyncio.Lock] = {}
		self._account_lock_mutex = asyncio.Lock()
		self._running_tasks: dict[str, asyncio.Task] = {}
		self._cancel_events: dict[str, asyncio.Event] = {}

	async def submit(self, task: Task) -> None:
		"""Submit a task for execution. Non-blocking.

		The task will wait for:
		1. A global semaphore slot (if at max concurrent)
		2. The per-account lock (if another task for same account is running)

		Args:
			task: The task to execute.
		"""
		cancel_event = asyncio.Event()
		self._cancel_events[task.id] = cancel_event

		async_task = asyncio.create_task(self._execute_with_limits(task, cancel_event))
		self._running_tasks[task.id] = async_task

		# Clean up when done
		async_task.add_done_callback(lambda t: self._on_task_done(task.id))

		logger.info("Task %s submitted to pool", task.id)

	def _on_task_done(self, task_id: str) -> None:
		"""Clean up resources when a task finishes."""
		self._running_tasks.pop(task_id, None)
		self._cancel_events.pop(task_id, None)

	async def _execute_with_limits(self, task: Task, cancel_event: asyncio.Event) -> None:
		"""Execute a task respecting concurrency limits."""
		account_id = task.account_id or "__no_account__"

		async with self._global_semaphore:
			account_lock = await self._get_account_lock(account_id)
			async with account_lock:
				logger.info("Task %s starting execution (account=%s)", task.id, account_id)
				try:
					await self._executor.execute(task, cancel_event=cancel_event)
				except asyncio.CancelledError:
					logger.info("Task %s was cancelled", task.id)
				except Exception:
					logger.exception("Task %s raised an unhandled exception", task.id)

	async def _get_account_lock(self, account_id: str) -> asyncio.Lock:
		"""Get or create a lock for the given account_id."""
		async with self._account_lock_mutex:
			if account_id not in self._account_locks:
				self._account_locks[account_id] = asyncio.Lock()
			return self._account_locks[account_id]

	def pending_count(self) -> int:
		"""Return the number of currently running/pending tasks."""
		return len(self._running_tasks)

	def get_running_task_ids(self) -> list[str]:
		"""Return IDs of currently running tasks."""
		return list(self._running_tasks.keys())

	async def cancel(self, task_id: str) -> bool:
		"""Cancel a running task. Signals the cancel event and cancels the asyncio task.

		Returns True if the task was found and cancellation was triggered.
		"""
		# Signal the cancel event so the executor can clean up gracefully
		cancel_event = self._cancel_events.get(task_id)
		if cancel_event:
			cancel_event.set()

		# Also cancel the asyncio task
		async_task = self._running_tasks.get(task_id)
		if async_task and not async_task.done():
			async_task.cancel()
			try:
				await asyncio.wait_for(async_task, timeout=10.0)
			except (asyncio.CancelledError, asyncio.TimeoutError):
				pass
			return True
		return False

	async def shutdown(self) -> None:
		"""Cancel all running tasks and wait for them to finish."""
		for task_id in list(self._running_tasks.keys()):
			await self.cancel(task_id)
		logger.info("TaskExecutorPool shutdown complete")
