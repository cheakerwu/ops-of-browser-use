from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str


class AccountStatus(str, Enum):
	ACTIVE = "active"
	DISABLED = "disabled"
	NEEDS_LOGIN = "needs_login"


class Account(BaseModel):
	model_config = ConfigDict(extra='forbid', validate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	name: str  # 显示名，如 "美团-朝阳店"
	platform: str  # meituan / douyin / taobao
	username: str | None = None  # 登录用户名（可选）
	profile_dir: str  # 浏览器 profile 目录路径
	status: AccountStatus = AccountStatus.NEEDS_LOGIN
	created_at: datetime = Field(default_factory=datetime.now)
	last_used_at: datetime | None = None
