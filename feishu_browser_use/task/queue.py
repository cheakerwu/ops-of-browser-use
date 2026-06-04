"""Async task queue with SQLite persistence and in-memory scheduling."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import aiosqlite

from feishu_browser_use.task.models import Task, TaskResult, TaskStatus

logger = logging.getLogger(__name__)

_RECOVERABLE_STATUSES = (
	TaskStatus.PENDING,
	TaskStatus.PARSING,
	TaskStatus.PREPARING,
	TaskStatus.AWAITING_APPROVAL,
)

_TERMINAL_STATUSES = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
	id TEXT PRIMARY KEY,
	user_id TEXT NOT NULL,
	chat_id TEXT NOT NULL,
	platform TEXT NOT NULL,
	instruction TEXT NOT NULL,
	account_id TEXT,
	status TEXT NOT NULL,
	approval_id TEXT,
	result TEXT,
	error TEXT,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
)
"""

_ADD_ACCOUNT_ID_COLUMN_SQL = """
ALTER TABLE tasks ADD COLUMN account_id TEXT
"""

_INSERT_SQL = """
INSERT INTO tasks (id, user_id, chat_id, platform, instruction, account_id, status, approval_id, result, error, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_BY_ID_SQL = "SELECT * FROM tasks WHERE id = ?"

_UPDATE_STATUS_SQL = """
UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?
"""

_UPDATE_FIELD_SQL = "UPDATE tasks SET {col} = ?, updated_at = ? WHERE id = ?"

_SELECT_NON_TERMINAL_SQL = (
	"SELECT * FROM tasks WHERE status NOT IN ({placeholders})".format(
		placeholders=", ".join("?" for _ in _TERMINAL_STATUSES)
	)
)

_SELECT_RECOVERABLE_SQL = (
	"SELECT * FROM tasks WHERE status IN ({placeholders})".format(
		placeholders=", ".join("?" for _ in _RECOVERABLE_STATUSES)
	)
)


def _row_to_task(row: aiosqlite.Row) -> Task:
	"""Convert a SQLite row to a Task instance."""
	data = dict(row)
	if data.get("result"):
		data["result"] = json.loads(data["result"])
	data["created_at"] = datetime.fromisoformat(data["created_at"])
	data["updated_at"] = datetime.fromisoformat(data["updated_at"])
	return Task.model_validate(data)


def _task_to_row(task: Task) -> tuple:
	"""Convert a Task instance to a row tuple for insertion."""
	return (
		task.id,
		task.user_id,
		task.chat_id,
		task.platform,
		task.instruction,
		task.account_id,
		task.status.value,
		task.approval_id,
		json.dumps(task.result.model_dump()) if task.result else None,
		task.error,
		task.created_at.isoformat(),
		task.updated_at.isoformat(),
	)


class TaskQueue:
	"""Async task queue backed by SQLite for persistence and asyncio.Queue for scheduling."""

	def __init__(self, db_path: str = "tasks.db") -> None:
		self._db_path = db_path
		self._db: aiosqlite.Connection | None = None
		self._queue: asyncio.Queue[str] = asyncio.Queue()
		self._started = False

	async def start(self) -> None:
		"""Initialize SQLite connection, create tables, and recover pending tasks."""
		if self._started:
			return

		self._db = await aiosqlite.connect(self._db_path)
		self._db.row_factory = aiosqlite.Row
		await self._db.execute(_CREATE_TABLE_SQL)
		await self._db.commit()

		# Schema migration: add account_id column if it doesn't exist
		try:
			await self._db.execute(_ADD_ACCOUNT_ID_COLUMN_SQL)
			await self._db.commit()
		except Exception:
			# Column already exists, ignore
			pass

		# Recover non-terminal tasks back into the in-memory queue
		status_values = [s.value for s in _RECOVERABLE_STATUSES]
		async with self._db.execute(_SELECT_RECOVERABLE_SQL, status_values) as cursor:
			rows = await cursor.fetchall()
			for row in rows:
				await self._queue.put(row["id"])

		logger.info("TaskQueue started, recovered %d tasks", len(rows))
		self._started = True

	async def submit(self, task: Task) -> str:
		"""Insert a task into the database and enqueue it. Returns the task id."""
		self._ensure_started()
		assert self._db is not None

		await self._db.execute(_INSERT_SQL, _task_to_row(task))
		await self._db.commit()
		await self._queue.put(task.id)

		logger.info("Task submitted: %s", task.id)
		return task.id

	async def get_task(self, task_id: str) -> Task | None:
		"""Retrieve a task by its id."""
		self._ensure_started()
		assert self._db is not None

		async with self._db.execute(_SELECT_BY_ID_SQL, (task_id,)) as cursor:
			row = await cursor.fetchone()
			if row is None:
				return None
			return _row_to_task(row)

	async def update_status(self, task_id: str, status: TaskStatus, **kwargs: Any) -> None:
		"""Update a task's status and optionally other fields.

		Supported kwargs: approval_id, result (TaskResult), error.
		"""
		self._ensure_started()
		assert self._db is not None

		now = datetime.now().isoformat()

		# Update status first
		await self._db.execute(_UPDATE_STATUS_SQL, (status.value, now, task_id))

		# Update any additional fields passed via kwargs
		field_handlers: dict[str, object] = {
			"approval_id": kwargs.get("approval_id"),
			"result": json.dumps(kwargs["result"].model_dump()) if "result" in kwargs and kwargs["result"] else None,
			"error": kwargs.get("error"),
		}

		for col, value in field_handlers.items():
			if col in kwargs:
				sql = _UPDATE_FIELD_SQL.format(col=col)
				await self._db.execute(sql, (value, now, task_id))

		await self._db.commit()
		logger.info("Task %s updated to %s", task_id, status.value)

	async def get_pending_tasks(self) -> list[Task]:
		"""Get all tasks whose status is not terminal (COMPLETED or FAILED)."""
		self._ensure_started()
		assert self._db is not None

		status_values = [s.value for s in _TERMINAL_STATUSES]
		async with self._db.execute(_SELECT_NON_TERMINAL_SQL, status_values) as cursor:
			rows = await cursor.fetchall()
			return [_row_to_task(row) for row in rows]

	async def cancel(self, task_id: str) -> bool:
		"""Cancel a task. Returns True if the task was cancelled."""
		task = await self.get_task(task_id)
		if task is None:
			return False
		if task.status in _TERMINAL_STATUSES:
			return False

		await self.update_status(task_id, TaskStatus.CANCELLED, error="用户取消")
		logger.info("Task cancelled: %s", task_id)
		return True

	async def process_next(self, timeout: float = 5.0) -> Task | None:
		"""Get the next task from the in-memory queue.

		Blocks up to *timeout* seconds waiting for a task.
		Returns None if the queue is empty after the timeout.
		The returned task is looked up from the database so its
		status is always fresh.
		"""
		self._ensure_started()

		try:
			task_id = await asyncio.wait_for(self._queue.get(), timeout=timeout)
		except asyncio.TimeoutError:
			return None

		task = await self.get_task(task_id)
		if task is None:
			# Task was deleted between enqueue and dequeue; skip.
			return None

		# Only return tasks that are still in a recoverable state.
		if task.status not in _RECOVERABLE_STATUSES:
			return None

		return task

	async def close(self) -> None:
		"""Close the database connection and drain the queue."""
		if self._db is not None:
			await self._db.close()
			self._db = None
		# Drain the queue so nothing blocks on it.
		while not self._queue.empty():
			try:
				self._queue.get_nowait()
			except asyncio.QueueEmpty:
				break
		self._started = False
		logger.info("TaskQueue closed")

	def _ensure_started(self) -> None:
		if not self._started:
			raise RuntimeError("TaskQueue has not been started. Call start() first.")
