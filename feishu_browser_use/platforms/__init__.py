"""Platform-specific implementations for Feishu Browser Use."""

from feishu_browser_use.platforms.base import PlatformAdapter
from feishu_browser_use.platforms.douyin import DouyinAdapter
from feishu_browser_use.platforms.meituan import MeituanAdapter
from feishu_browser_use.platforms.taobao import TaobaoAdapter

_ADAPTERS: dict[str, PlatformAdapter] = {
	"meituan": MeituanAdapter(),
	"douyin": DouyinAdapter(),
	"taobao": TaobaoAdapter(),
}


def get_adapter(platform: str) -> PlatformAdapter:
	"""Get a platform adapter by name.

	Args:
		platform: Platform identifier (meituan / douyin / taobao).

	Returns:
		The corresponding PlatformAdapter instance.

	Raises:
		ValueError: If the platform is not supported.
	"""
	adapter = _ADAPTERS.get(platform.lower())
	if adapter is None:
		supported = ", ".join(_ADAPTERS.keys())
		raise ValueError(f"Unsupported platform: {platform!r}. Supported: {supported}")
	return adapter


__all__ = ["PlatformAdapter", "DouyinAdapter", "MeituanAdapter", "TaobaoAdapter", "get_adapter"]