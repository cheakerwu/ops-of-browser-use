from datetime import datetime
from types import SimpleNamespace

import pytest

import feishu_browser_use.server as server


class FakeAccountManager:
	def __init__(self, accounts):
		self._accounts = accounts

	async def find_account_for_message(self, keyword, platform=None):
		matches = [account for account in self._accounts if keyword in account.name]
		if platform:
			matches = [account for account in matches if account.platform == platform]
		return matches

	async def get_accounts_by_platform(self, platform):
		return [account for account in self._accounts if account.platform == platform]


@pytest.mark.asyncio
async def test_parse_compact_open_command_reuses_matching_account(monkeypatch):
	account = SimpleNamespace(
		id="acc-1",
		name="江湖饭焗",
		platform="meituan",
		created_at=datetime(2026, 1, 1),
		last_used_at=datetime(2026, 1, 2),
	)
	monkeypatch.setattr(server, "_account_manager", FakeAccountManager([account]))

	platform, instruction, matched_account = await server._parse_message_with_account(
		"打开美团江湖饭焗",
		"user-1",
	)

	assert platform == "meituan"
	assert instruction == "打开"
	assert matched_account == account
