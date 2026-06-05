"""Structured intent parsing for user task instructions."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field


class ParsedIntent(BaseModel):
	model_config = ConfigDict(extra="forbid")

	intent: str
	target: str = ""
	params: dict = Field(default_factory=dict)
	confidence: float = 0.0


class IntentParser:
	"""Rule-based parser for common merchant operations.

	This intentionally runs before any LLM so policy and audit can work from
	stable structured fields.
	"""

	def parse(self, raw_text: str, platform: str, instruction: str) -> ParsedIntent:
		text = instruction.strip() or raw_text.strip()

		price = self._parse_change_price(text)
		if price is not None:
			return price

		if any(word in text for word in ("上传", "替换图片", "门店图", "商品图", "菜单图", "图片")):
			target = "门店图" if "门店" in text else "图片"
			return ParsedIntent(intent="update_image", target=target, confidence=0.8)

		if any(word in text for word in ("打开", "进入", "访问")):
			return ParsedIntent(
				intent="open_merchant_backend",
				target="merchant_backend",
				confidence=0.95,
			)

		if any(word in text for word in ("登录", "重新登录")):
			return ParsedIntent(intent="login", target="merchant_backend", confidence=0.9)

		return ParsedIntent(intent="general_task", target="", confidence=0.3)

	def _parse_change_price(self, text: str) -> ParsedIntent | None:
		m = re.search(
			r"(?P<target>.+?)\s*价格\s*(?:改成|改为|调为|设为|设成)\s*(?P<price>\d+(?:\.\d+)?)\s*(?:元)?",
			text,
		)
		if not m:
			return None

		target = m.group("target").strip()
		for prefix in ("把", "将"):
			if target.startswith(prefix):
				target = target[len(prefix):].strip()

		return ParsedIntent(
			intent="change_price",
			target=target,
			params={"price": float(m.group("price"))},
			confidence=0.9,
		)
