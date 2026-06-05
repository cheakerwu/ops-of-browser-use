from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str


class TaskStatus(str, Enum):
	PENDING = "pending"
	PARSING = "parsing"
	PREPARING = "preparing"
	AWAITING_APPROVAL = "awaiting_approval"
	EXECUTING = "executing"
	COMPLETED = "completed"
	FAILED = "failed"
	CANCELLED = "cancelled"


class TaskResult(BaseModel):
	model_config = ConfigDict(extra='forbid', validate_by_name=True)

	success: bool
	message: str
	screenshots: list[str] = Field(default_factory=list)
	details: dict = Field(default_factory=dict)


class Task(BaseModel):
	model_config = ConfigDict(extra='forbid', validate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	user_id: str
	chat_id: str
	message_id: str | None = None
	task_card_message_id: str | None = None
	tenant_key: str | None = None
	raw_text: str | None = None
	platform: str
	instruction: str
	account_id: str | None = None  # 关联的账号 ID
	intent: str | None = None
	intent_target: str | None = None
	intent_params: dict = Field(default_factory=dict)
	intent_confidence: float | None = None
	prompt_version: str | None = None
	policy_status: str | None = None
	policy_reason: str | None = None
	allowed_domains: list[str] = Field(default_factory=list)
	status: TaskStatus = TaskStatus.PENDING
	approval_id: str | None = None
	result: TaskResult | None = None
	error: str | None = None
	error_type: str | None = None
	error_message_user: str | None = None
	error_message_internal: str | None = None
	created_at: datetime = Field(default_factory=datetime.now)
	updated_at: datetime = Field(default_factory=datetime.now)


class TaskEvent(BaseModel):
	model_config = ConfigDict(extra='forbid', validate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	task_id: str
	event_type: str
	message: str
	details: dict = Field(default_factory=dict)
	created_at: datetime = Field(default_factory=datetime.now)


class TaskMetricBucket(BaseModel):
	model_config = ConfigDict(extra='forbid', validate_by_name=True)

	total: int = 0
	completed: int = 0
	failed: int = 0
	cancelled: int = 0


class TaskMetrics(BaseModel):
	model_config = ConfigDict(extra='forbid', validate_by_name=True)

	total_tasks: int = 0
	terminal_tasks: int = 0
	completed_tasks: int = 0
	failed_tasks: int = 0
	cancelled_tasks: int = 0
	success_rate: float = 0
	failure_rate: float = 0
	average_duration_seconds: float = 0
	by_platform: dict[str, TaskMetricBucket] = Field(default_factory=dict)
	by_intent: dict[str, TaskMetricBucket] = Field(default_factory=dict)
	error_types: dict[str, int] = Field(default_factory=dict)


class Attachment(BaseModel):
	model_config = ConfigDict(extra='forbid', validate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	tenant_key: str | None = None
	chat_id: str | None = None
	message_id: str | None = None
	uploaded_by_user_id: str | None = None
	file_type: str
	file_name: str | None = None
	mime_type: str | None = None
	feishu_file_key: str | None = None
	local_path: str | None = None
	sha256: str | None = None
	size_bytes: int | None = None
	status: str = "stored"
	created_at: datetime = Field(default_factory=datetime.now)
	expires_at: datetime | None = None
