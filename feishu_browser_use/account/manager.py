"""Account manager with SQLite persistence and browser profile directory management."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from feishu_browser_use.account.models import Account, AccountStatus

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
	id TEXT PRIMARY KEY,
	name TEXT NOT NULL,
	platform TEXT NOT NULL,
	username TEXT,
	profile_dir TEXT NOT NULL,
	status TEXT NOT NULL DEFAULT 'needs_login',
	created_at TEXT NOT NULL,
	last_used_at TEXT
)
"""

_INSERT_SQL = """
INSERT INTO accounts (id, name, platform, username, profile_dir, status, created_at, last_used_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_BY_ID_SQL = "SELECT * FROM accounts WHERE id = ?"

_SELECT_BY_PLATFORM_SQL = "SELECT * FROM accounts WHERE platform = ? AND status != 'disabled'"

_SEARCH_BY_NAME_SQL = "SELECT * FROM accounts WHERE name LIKE ? AND status != 'disabled'"

_SELECT_ALL_SQL = "SELECT * FROM accounts WHERE status != 'disabled'"

_UPDATE_STATUS_SQL = "UPDATE accounts SET status = ?, last_used_at = ? WHERE id = ?"

_UPDATE_LAST_USED_SQL = "UPDATE accounts SET last_used_at = ? WHERE id = ?"

_DELETE_SQL = "DELETE FROM accounts WHERE id = ?"


def _row_to_account(row: aiosqlite.Row) -> Account:
	"""Convert a SQLite row to an Account instance."""
	data = dict(row)
	data["created_at"] = datetime.fromisoformat(data["created_at"])
	if data.get("last_used_at"):
		data["last_used_at"] = datetime.fromisoformat(data["last_used_at"])
	return Account.model_validate(data)


def _account_to_row(account: Account) -> tuple:
	"""Convert an Account instance to a row tuple for insertion."""
	return (
		account.id,
		account.name,
		account.platform,
		account.username,
		account.profile_dir,
		account.status.value,
		account.created_at.isoformat(),
		account.last_used_at.isoformat() if account.last_used_at else None,
	)


class AccountManager:
	"""Manages platform accounts with SQLite persistence and browser profile directories."""

	def __init__(self, db_path: str = "tasks.db", profiles_base_dir: str | None = None) -> None:
		self._db_path = db_path
		self._profiles_base = Path(profiles_base_dir) if profiles_base_dir else Path.home() / ".feishu-browser-use" / "profiles"
		self._db: aiosqlite.Connection | None = None
		self._started = False

	async def start(self) -> None:
		"""Initialize SQLite connection and create tables."""
		if self._started:
			return

		self._db = await aiosqlite.connect(self._db_path)
		self._db.row_factory = aiosqlite.Row
		await self._db.execute(_CREATE_TABLE_SQL)
		await self._db.commit()

		self._profiles_base.mkdir(parents=True, exist_ok=True)

		logger.info("AccountManager started, profiles dir: %s", self._profiles_base)
		self._started = True

	async def create_account(
		self,
		name: str,
		platform: str,
		username: str | None = None,
	) -> Account:
		"""Create a new account with a dedicated browser profile directory.

		Args:
			name: Display name for the account (e.g. "美团-朝阳店").
			platform: Platform identifier (meituan / douyin / taobao).
			username: Optional login username.

		Returns:
			The newly created Account.
		"""
		self._ensure_started()
		assert self._db is not None

		account = Account(
			name=name,
			platform=platform,
			username=username,
			profile_dir="",  # will be set below
		)

		# Set profile dir based on account id
		profile_path = self._profiles_base / account.id
		account.profile_dir = str(profile_path)
		profile_path.mkdir(parents=True, exist_ok=True)

		await self._db.execute(_INSERT_SQL, _account_to_row(account))
		await self._db.commit()

		logger.info("Account created: %s (%s/%s)", account.id, platform, name)
		return account

	async def get_account(self, account_id: str) -> Account | None:
		"""Retrieve an account by its id."""
		self._ensure_started()
		assert self._db is not None

		async with self._db.execute(_SELECT_BY_ID_SQL, (account_id,)) as cursor:
			row = await cursor.fetchone()
			return _row_to_account(row) if row else None

	async def search_accounts(self, keyword: str) -> list[Account]:
		"""Search accounts by name (fuzzy match).

		Args:
			keyword: Search keyword to match against account name.

		Returns:
			List of matching accounts.
		"""
		self._ensure_started()
		assert self._db is not None

		async with self._db.execute(_SEARCH_BY_NAME_SQL, (f"%{keyword}%",)) as cursor:
			rows = await cursor.fetchall()
			return [_row_to_account(row) for row in rows]

	async def get_accounts_by_platform(self, platform: str) -> list[Account]:
		"""Get all active accounts for a platform."""
		self._ensure_started()
		assert self._db is not None

		async with self._db.execute(_SELECT_BY_PLATFORM_SQL, (platform,)) as cursor:
			rows = await cursor.fetchall()
			return [_row_to_account(row) for row in rows]

	async def get_all_accounts(self) -> list[Account]:
		"""Get all non-disabled accounts."""
		self._ensure_started()
		assert self._db is not None

		async with self._db.execute(_SELECT_ALL_SQL) as cursor:
			rows = await cursor.fetchall()
			return [_row_to_account(row) for row in rows]

	async def update_status(self, account_id: str, status: AccountStatus) -> None:
		"""Update an account's status."""
		self._ensure_started()
		assert self._db is not None

		now = datetime.now().isoformat()
		await self._db.execute(_UPDATE_STATUS_SQL, (status.value, now, account_id))
		await self._db.commit()
		logger.info("Account %s status updated to %s", account_id, status.value)

	async def touch(self, account_id: str) -> None:
		"""Update last_used_at to now."""
		self._ensure_started()
		assert self._db is not None

		now = datetime.now().isoformat()
		await self._db.execute(_UPDATE_LAST_USED_SQL, (now, account_id))
		await self._db.commit()

	async def delete_account(self, account_id: str) -> bool:
		"""Delete an account. Returns True if deleted."""
		self._ensure_started()
		assert self._db is not None

		async with self._db.execute(_SELECT_BY_ID_SQL, (account_id,)) as cursor:
			row = await cursor.fetchone()
			if row is None:
				return False

		await self._db.execute(_DELETE_SQL, (account_id,))
		await self._db.commit()
		logger.info("Account deleted: %s", account_id)
		return True

	async def find_account_for_message(self, keyword: str, platform: str | None = None) -> list[Account]:
		"""Find accounts matching a keyword, optionally filtered by platform.

		Used by message parsing to resolve account names from user messages.

		Args:
			keyword: Account name keyword from the message.
			platform: Optional platform filter.

		Returns:
			List of matching accounts (may be empty).
		"""
		candidates = await self.search_accounts(keyword)

		if platform:
			candidates = [a for a in candidates if a.platform == platform]

		return candidates

	async def close(self) -> None:
		"""Close the database connection."""
		if self._db is not None:
			await self._db.close()
			self._db = None
		self._started = False
		logger.info("AccountManager closed")

	def _ensure_started(self) -> None:
		if not self._started:
			raise RuntimeError("AccountManager has not been started. Call start() first.")
