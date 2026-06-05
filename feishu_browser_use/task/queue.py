"""Async task queue with SQLite persistence and in-memory scheduling."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import aiosqlite

from feishu_browser_use.task.models import Attachment, Task, TaskEvent, TaskMetricBucket, TaskMetrics, TaskResult, TaskStatus

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
	message_id TEXT,
	task_card_message_id TEXT,
	tenant_key TEXT,
	raw_text TEXT,
	platform TEXT NOT NULL,
	instruction TEXT NOT NULL,
	account_id TEXT,
	intent TEXT,
	intent_target TEXT,
	intent_params TEXT,
	intent_confidence REAL,
	prompt_version TEXT,
	policy_status TEXT,
	policy_reason TEXT,
	allowed_domains TEXT,
	status TEXT NOT NULL,
	approval_id TEXT,
	result TEXT,
	error TEXT,
	error_type TEXT,
	error_message_user TEXT,
	error_message_internal TEXT,
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
)
"""

_TASK_COLUMN_MIGRATIONS: dict[str, str] = {
	"account_id": "ALTER TABLE tasks ADD COLUMN account_id TEXT",
	"message_id": "ALTER TABLE tasks ADD COLUMN message_id TEXT",
	"task_card_message_id": "ALTER TABLE tasks ADD COLUMN task_card_message_id TEXT",
	"tenant_key": "ALTER TABLE tasks ADD COLUMN tenant_key TEXT",
	"raw_text": "ALTER TABLE tasks ADD COLUMN raw_text TEXT",
	"intent": "ALTER TABLE tasks ADD COLUMN intent TEXT",
	"intent_target": "ALTER TABLE tasks ADD COLUMN intent_target TEXT",
	"intent_params": "ALTER TABLE tasks ADD COLUMN intent_params TEXT",
	"intent_confidence": "ALTER TABLE tasks ADD COLUMN intent_confidence REAL",
	"prompt_version": "ALTER TABLE tasks ADD COLUMN prompt_version TEXT",
	"policy_status": "ALTER TABLE tasks ADD COLUMN policy_status TEXT",
	"policy_reason": "ALTER TABLE tasks ADD COLUMN policy_reason TEXT",
	"allowed_domains": "ALTER TABLE tasks ADD COLUMN allowed_domains TEXT",
	"error_type": "ALTER TABLE tasks ADD COLUMN error_type TEXT",
	"error_message_user": "ALTER TABLE tasks ADD COLUMN error_message_user TEXT",
	"error_message_internal": "ALTER TABLE tasks ADD COLUMN error_message_internal TEXT",
}

_CREATE_TASK_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS task_events (
	id TEXT PRIMARY KEY,
	task_id TEXT NOT NULL,
	event_type TEXT NOT NULL,
	message TEXT NOT NULL,
	details TEXT,
	created_at TEXT NOT NULL
)
"""

_CREATE_ATTACHMENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS attachments (
	id TEXT PRIMARY KEY,
	tenant_key TEXT,
	chat_id TEXT,
	message_id TEXT,
	uploaded_by_user_id TEXT,
	file_type TEXT NOT NULL,
	file_name TEXT,
	mime_type TEXT,
	feishu_file_key TEXT,
	local_path TEXT,
	sha256 TEXT,
	size_bytes INTEGER,
	status TEXT NOT NULL,
	created_at TEXT NOT NULL,
	expires_at TEXT
)
"""

_CREATE_TASK_ATTACHMENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS task_attachments (
	task_id TEXT NOT NULL,
	attachment_id TEXT NOT NULL,
	purpose TEXT NOT NULL,
	PRIMARY KEY (task_id, attachment_id, purpose)
)
"""

_INSERT_ATTACHMENT_SQL = """
INSERT INTO attachments (
	id, tenant_key, chat_id, message_id, uploaded_by_user_id, file_type,
	file_name, mime_type, feishu_file_key, local_path, sha256, size_bytes,
	status, created_at, expires_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_ATTACHMENT_SQL = "SELECT * FROM attachments WHERE id = ?"

_INSERT_TASK_ATTACHMENT_SQL = """
INSERT OR IGNORE INTO task_attachments (task_id, attachment_id, purpose)
VALUES (?, ?, ?)
"""

_SELECT_TASK_ATTACHMENTS_SQL = """
SELECT a.* FROM attachments a
JOIN task_attachments ta ON ta.attachment_id = a.id
WHERE ta.task_id = ?
ORDER BY a.created_at ASC
"""

_SELECT_RECENT_ATTACHMENTS_SQL = """
SELECT * FROM attachments
WHERE chat_id = ?
  AND (? IS NULL OR uploaded_by_user_id = ?)
ORDER BY created_at DESC
LIMIT ?
"""

_INSERT_SQL = """
INSERT INTO tasks (
	id, user_id, chat_id, message_id, task_card_message_id, tenant_key, raw_text,
	platform, instruction, account_id, intent, intent_target, intent_params,
	intent_confidence, prompt_version, policy_status, policy_reason,
	allowed_domains, status, approval_id, result, error, error_type,
	error_message_user, error_message_internal, created_at, updated_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_EVENT_SQL = """
INSERT INTO task_events (id, task_id, event_type, message, details, created_at)
VALUES (?, ?, ?, ?, ?, ?)
"""

_SELECT_EVENTS_SQL = "SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at ASC"

_SELECT_BY_ID_SQL = "SELECT * FROM tasks WHERE id = ?"

_SELECT_BY_PREFIX_SQL = "SELECT * FROM tasks WHERE id LIKE ? ORDER BY created_at DESC LIMIT 1"

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
	if data.get("allowed_domains"):
		data["allowed_domains"] = json.loads(data["allowed_domains"])
	else:
		data["allowed_domains"] = []
	if data.get("intent_params"):
		data["intent_params"] = json.loads(data["intent_params"])
	else:
		data["intent_params"] = {}
	data["created_at"] = datetime.fromisoformat(data["created_at"])
	data["updated_at"] = datetime.fromisoformat(data["updated_at"])
	return Task.model_validate(data)


def _task_to_row(task: Task) -> tuple:
	"""Convert a Task instance to a row tuple for insertion."""
	return (
		task.id,
		task.user_id,
		task.chat_id,
		task.message_id,
		task.task_card_message_id,
		task.tenant_key,
		task.raw_text,
		task.platform,
		task.instruction,
		task.account_id,
		task.intent,
		task.intent_target,
		json.dumps(task.intent_params, ensure_ascii=False),
		task.intent_confidence,
		task.prompt_version,
		task.policy_status,
		task.policy_reason,
		json.dumps(task.allowed_domains),
		task.status.value,
		task.approval_id,
		json.dumps(task.result.model_dump()) if task.result else None,
		task.error,
		task.error_type,
		task.error_message_user,
		task.error_message_internal,
		task.created_at.isoformat(),
		task.updated_at.isoformat(),
	)


def _row_to_event(row: aiosqlite.Row) -> TaskEvent:
	data = dict(row)
	data["details"] = json.loads(data["details"]) if data.get("details") else {}
	data["created_at"] = datetime.fromisoformat(data["created_at"])
	return TaskEvent.model_validate(data)


def _event_to_row(event: TaskEvent) -> tuple:
	return (
		event.id,
		event.task_id,
		event.event_type,
		event.message,
		json.dumps(event.details),
		event.created_at.isoformat(),
	)


def _attachment_to_row(attachment: Attachment) -> tuple:
	return (
		attachment.id,
		attachment.tenant_key,
		attachment.chat_id,
		attachment.message_id,
		attachment.uploaded_by_user_id,
		attachment.file_type,
		attachment.file_name,
		attachment.mime_type,
		attachment.feishu_file_key,
		attachment.local_path,
		attachment.sha256,
		attachment.size_bytes,
		attachment.status,
		attachment.created_at.isoformat(),
		attachment.expires_at.isoformat() if attachment.expires_at else None,
	)


def _row_to_attachment(row: aiosqlite.Row) -> Attachment:
	data = dict(row)
	data["created_at"] = datetime.fromisoformat(data["created_at"])
	if data.get("expires_at"):
		data["expires_at"] = datetime.fromisoformat(data["expires_at"])
	return Attachment.model_validate(data)


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
		await self._db.execute(_CREATE_TASK_EVENTS_TABLE_SQL)
		await self._db.execute(_CREATE_ATTACHMENTS_TABLE_SQL)
		await self._db.execute(_CREATE_TASK_ATTACHMENTS_TABLE_SQL)
		await self._db.commit()

		await self._migrate_task_columns()

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
		await self._insert_event(
			TaskEvent(
				task_id=task.id,
				event_type="created",
				message="任务已创建",
				details={
					"platform": task.platform,
					"account_id": task.account_id,
					"intent": task.intent,
					"policy_status": task.policy_status,
				},
			)
		)
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

	async def get_task_by_prefix(self, task_id_prefix: str) -> Task | None:
		"""Retrieve a task by its id prefix (first 8+ chars)."""
		self._ensure_started()
		assert self._db is not None

		async with self._db.execute(_SELECT_BY_PREFIX_SQL, (f"{task_id_prefix}%",)) as cursor:
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
			"error_type": kwargs.get("error_type"),
			"error_message_user": kwargs.get("error_message_user"),
			"error_message_internal": kwargs.get("error_message_internal"),
		}

		for col, value in field_handlers.items():
			if col in kwargs:
				sql = _UPDATE_FIELD_SQL.format(col=col)
				await self._db.execute(sql, (value, now, task_id))

		await self._insert_event(
			TaskEvent(
				task_id=task_id,
				event_type=status.value,
				message=self._status_event_message(status),
				details={
					"error": kwargs.get("error"),
					"error_type": kwargs.get("error_type"),
					"error_message_user": kwargs.get("error_message_user"),
				},
			)
		)
		await self._db.commit()
		logger.info("Task %s updated to %s", task_id, status.value)

	async def add_event(self, task_id: str, event_type: str, message: str, details: dict | None = None) -> None:
		"""Append an event to a task's audit timeline."""
		self._ensure_started()
		assert self._db is not None
		await self._insert_event(
			TaskEvent(
				task_id=task_id,
				event_type=event_type,
				message=message,
				details=details or {},
			)
		)
		await self._db.commit()

	async def set_task_card_message_id(self, task_id: str, message_id: str) -> None:
		"""Persist the Feishu message id for the task card."""
		self._ensure_started()
		assert self._db is not None
		now = datetime.now().isoformat()
		await self._db.execute(
			_UPDATE_FIELD_SQL.format(col="task_card_message_id"),
			(message_id, now, task_id),
		)
		await self._insert_event(
			TaskEvent(
				task_id=task_id,
				event_type="task_card_created",
				message="任务卡片已创建",
				details={"message_id": message_id},
			)
		)
		await self._db.commit()

	async def get_events(self, task_id: str) -> list[TaskEvent]:
		"""Return task events in creation order."""
		self._ensure_started()
		assert self._db is not None
		async with self._db.execute(_SELECT_EVENTS_SQL, (task_id,)) as cursor:
			rows = await cursor.fetchall()
			return [_row_to_event(row) for row in rows]

	async def get_metrics(self) -> TaskMetrics:
		"""Aggregate task success, failure, duration, platform, and intent metrics."""
		self._ensure_started()
		assert self._db is not None

		async with self._db.execute(
			"SELECT platform, intent, status, error_type, created_at, updated_at FROM tasks"
		) as cursor:
			rows = await cursor.fetchall()

		metrics = TaskMetrics(total_tasks=len(rows))
		durations: list[float] = []

		for row in rows:
			status = row["status"]
			platform = row["platform"] or "unknown"
			intent = row["intent"] or "unknown"

			platform_bucket = metrics.by_platform.setdefault(platform, TaskMetricBucket())
			intent_bucket = metrics.by_intent.setdefault(intent, TaskMetricBucket())
			for bucket in (platform_bucket, intent_bucket):
				bucket.total += 1
				if status == TaskStatus.COMPLETED.value:
					bucket.completed += 1
				elif status == TaskStatus.FAILED.value:
					bucket.failed += 1
				elif status == TaskStatus.CANCELLED.value:
					bucket.cancelled += 1

			if status == TaskStatus.COMPLETED.value:
				metrics.completed_tasks += 1
			elif status == TaskStatus.FAILED.value:
				metrics.failed_tasks += 1
				error_type = row["error_type"] or "unknown"
				metrics.error_types[error_type] = metrics.error_types.get(error_type, 0) + 1
			elif status == TaskStatus.CANCELLED.value:
				metrics.cancelled_tasks += 1

			if status in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
				metrics.terminal_tasks += 1
				try:
					created_at = datetime.fromisoformat(row["created_at"])
					updated_at = datetime.fromisoformat(row["updated_at"])
					durations.append(max(0, (updated_at - created_at).total_seconds()))
				except Exception:
					pass

		if metrics.terminal_tasks:
			metrics.success_rate = metrics.completed_tasks / metrics.terminal_tasks
			metrics.failure_rate = metrics.failed_tasks / metrics.terminal_tasks
		if durations:
			metrics.average_duration_seconds = sum(durations) / len(durations)

		return metrics

	async def add_attachment(self, attachment: Attachment) -> str:
		"""Persist attachment metadata for future task execution."""
		self._ensure_started()
		assert self._db is not None
		await self._db.execute(_INSERT_ATTACHMENT_SQL, _attachment_to_row(attachment))
		await self._db.commit()
		return attachment.id

	async def get_attachment(self, attachment_id: str) -> Attachment | None:
		"""Return an attachment by id."""
		self._ensure_started()
		assert self._db is not None
		async with self._db.execute(_SELECT_ATTACHMENT_SQL, (attachment_id,)) as cursor:
			row = await cursor.fetchone()
			return _row_to_attachment(row) if row else None

	async def link_attachment(self, task_id: str, attachment_id: str, purpose: str) -> None:
		"""Link an attachment to a task with a semantic purpose."""
		self._ensure_started()
		assert self._db is not None
		await self._db.execute(_INSERT_TASK_ATTACHMENT_SQL, (task_id, attachment_id, purpose))
		await self._insert_event(
			TaskEvent(
				task_id=task_id,
				event_type="attachment_linked",
				message="附件已关联到任务",
				details={"attachment_id": attachment_id, "purpose": purpose},
			)
		)
		await self._db.commit()

	async def get_task_attachments(self, task_id: str) -> list[Attachment]:
		"""Return attachments linked to a task."""
		self._ensure_started()
		assert self._db is not None
		async with self._db.execute(_SELECT_TASK_ATTACHMENTS_SQL, (task_id,)) as cursor:
			rows = await cursor.fetchall()
			return [_row_to_attachment(row) for row in rows]

	async def get_recent_attachments(
		self,
		chat_id: str,
		user_id: str | None = None,
		limit: int = 5,
	) -> list[Attachment]:
		"""Return recent attachment metadata for a chat, optionally scoped to a user."""
		self._ensure_started()
		assert self._db is not None
		async with self._db.execute(
			_SELECT_RECENT_ATTACHMENTS_SQL,
			(chat_id, user_id, user_id, limit),
		) as cursor:
			rows = await cursor.fetchall()
			return [_row_to_attachment(row) for row in rows]

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

	async def _migrate_task_columns(self) -> None:
		assert self._db is not None
		async with self._db.execute("PRAGMA table_info(tasks)") as cursor:
			existing_columns = {row["name"] for row in await cursor.fetchall()}
		for column, sql in _TASK_COLUMN_MIGRATIONS.items():
			if column not in existing_columns:
				await self._db.execute(sql)
		await self._db.commit()

	async def _insert_event(self, event: TaskEvent) -> None:
		assert self._db is not None
		await self._db.execute(_INSERT_EVENT_SQL, _event_to_row(event))

	def _status_event_message(self, status: TaskStatus) -> str:
		return {
			TaskStatus.PENDING: "任务等待中",
			TaskStatus.PARSING: "正在解析任务",
			TaskStatus.PREPARING: "正在准备任务",
			TaskStatus.AWAITING_APPROVAL: "等待确认",
			TaskStatus.EXECUTING: "任务开始执行",
			TaskStatus.COMPLETED: "任务执行成功",
			TaskStatus.FAILED: "任务执行失败",
			TaskStatus.CANCELLED: "任务已取消",
		}.get(status, f"任务状态更新为 {status.value}")
