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
	platform: str
	instruction: str
	account_id: str | None = None  # 关联的账号 ID
	status: TaskStatus = TaskStatus.PENDING
	approval_id: str | None = None
	result: TaskResult | None = None
	error: str | None = None
	created_at: datetime = Field(default_factory=datetime.now)
	updated_at: datetime = Field(default_factory=datetime.now)
