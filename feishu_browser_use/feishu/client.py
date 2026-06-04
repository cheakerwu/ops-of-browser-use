"""Feishu Lark API client singleton."""

import lark_oapi as lark

from feishu_browser_use.config import get_config

_client: lark.Client | None = None


def get_feishu_client() -> lark.Client:
	"""Return a singleton lark.Client configured from environment settings.

	The client automatically manages tenant_access_token refresh.
	"""
	global _client
	if _client is None:
		config = get_config()
		_client = (
			lark.Client.builder()
			.app_id(config.FEISHU_APP_ID)
			.app_secret(config.FEISHU_APP_SECRET)
			.log_level(lark.LogLevel.INFO)
			.build()
		)
	return _client
