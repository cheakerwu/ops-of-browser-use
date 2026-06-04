"""Parse natural language task instructions into structured task info."""

from __future__ import annotations

import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

# Supported platforms and their aliases
PLATFORM_ALIASES: dict[str, str] = {
	"美团": "meituan",
	"饿了么": "eleme",
	"抖音": "douyin",
	"快手": "kuaishou",
	"淘宝": "taobao",
	"天猫": "tmall",
	"京东": "jd",
	"拼多多": "pinduoduo",
	"meituan": "meituan",
	"eleme": "eleme",
	"douyin": "douyin",
	"kuaishou": "kuaishou",
	"taobao": "taobao",
	"tmall": "tmall",
	"jd": "jd",
	"pinduoduo": "pinduoduo",
}

# Action keywords mapping
ACTION_KEYWORDS: dict[str, str] = {
	"价格改成": "change_price",
	"价格改为": "change_price",
	"价格调为": "change_price",
	"改成价格": "change_price",
	"改为价格": "change_price",
	"调为价格": "change_price",
	"定价": "change_price",
	"降价": "decrease_price",
	"涨价": "increase_price",
	"加价": "increase_price",
	"库存改成": "change_stock",
	"库存改为": "change_stock",
	"库存调为": "change_stock",
	"补货": "change_stock",
	"下架": "delist",
	"上架": "list",
}


class TaskParser:
	"""Parse natural language instructions into structured task dicts."""

	def __init__(self, llm_base_url: str, llm_api_key: str, llm_model: str) -> None:
		self._llm_base_url = llm_base_url.rstrip("/")
		self._llm_api_key = llm_api_key
		self._llm_model = llm_model

	async def parse(self, instruction: str) -> dict:
		"""Parse a natural language instruction into structured task info.

		Tries regex-based parsing first for simple patterns,
		falls back to LLM-based parsing for complex cases.

		Returns dict with keys: platform, action, target, params.
		"""
		simple_result = self._parse_simple(instruction)
		if simple_result is not None:
			logger.debug("Regex parse succeeded for: %s", instruction)
			return simple_result

		logger.debug("Falling back to LLM parse for: %s", instruction)
		return await self._parse_with_llm(instruction)

	def _parse_simple(self, instruction: str) -> dict | None:
		"""Regex-based parsing for common simple patterns.

		Handles patterns like:
		- 把/将 [platform] [product] 价格改成/改为/调为 [price]
		- [platform] [product] 降价/涨价 [amount/percent]
		- 将 [platform] [product] 下架/上架

		Returns parsed dict or None if pattern doesn't match.
		"""
		# Normalize whitespace
		text = instruction.strip()

		# Pattern 1: 把/将 [platform] [product] 价格改成/改为/调为 [price]
		m = re.match(
			r"^(?:把|将)?\s*(\S+?)\s*(?:的)?\s*(.+?)\s*(?:的)?\s*价格\s*(?:改成|改为|调为|设为|设成)\s*(\d+(?:\.\d+)?)\s*(?:元)?\s*$",
			text,
		)
		if m:
			platform = self._resolve_platform(m.group(1))
			if platform:
				return {
					"platform": platform,
					"action": "change_price",
					"target": m.group(2).strip(),
					"params": {"price": float(m.group(3))},
				}

		# Pattern 2: [platform] [product] 降价/涨价 [amount/percent]
		m = re.match(
			r"^(\S+?)\s*(?:的)?\s*(.+?)\s*(降价|涨价|加价)\s*(\d+(?:\.\d+)?)\s*(元|%|百分|块)?\s*$",
			text,
		)
		if m:
			platform = self._resolve_platform(m.group(1))
			if platform:
				action = "decrease_price" if m.group(3) == "降价" else "increase_price"
				unit = m.group(5) or "元"
				is_percent = unit in ("%", "百分")
				return {
					"platform": platform,
					"action": action,
					"target": m.group(2).strip(),
					"params": {
						("percent" if is_percent else "amount"): float(m.group(4)),
					},
				}

		# Pattern 3: 将 [platform] [product] 库存改成/改为/调为 [stock]
		m = re.match(
			r"^(?:把|将)?\s*(\S+?)\s*(?:的)?\s*(.+?)\s*(?:的)?\s*库存\s*(?:改成|改为|调为|设为|设成)\s*(\d+)\s*$",
			text,
		)
		if m:
			platform = self._resolve_platform(m.group(1))
			if platform:
				return {
					"platform": platform,
					"action": "change_stock",
					"target": m.group(2).strip(),
					"params": {"stock": int(m.group(3))},
				}

		# Pattern 4: 将 [platform] [product] 下架/上架
		m = re.match(
			r"^(?:把|将)?\s*(\S+?)\s*(?:的)?\s*(.+?)\s*(下架|上架)\s*$",
			text,
		)
		if m:
			platform = self._resolve_platform(m.group(1))
			if platform:
				action = "delist" if m.group(3) == "下架" else "list"
				return {
					"platform": platform,
					"action": action,
					"target": m.group(2).strip(),
					"params": {},
				}

		return None

	async def _parse_with_llm(self, instruction: str) -> dict:
		"""LLM-based parsing for complex or unrecognized instructions.

		Sends the instruction to an OpenAI-compatible API and asks for
		JSON output matching the task schema.
		"""
		system_prompt = """你是一个任务解析助手。将用户的自然语言指令解析为结构化的 JSON。

必须返回一个 JSON 对象，包含以下字段：
- platform: 平台名称，必须是以下之一: meituan, eleme, douyin, kuaishou, taobao, tmall, jd, pinduoduo
- action: 操作类型，例如: change_price, change_stock, delist, list, update_description, 等
- target: 目标商品名称或ID
- params: 操作参数字典，例如 {"price": 99} 或 {"stock": 100}

只返回 JSON，不要有任何其他文字。如果信息不足，用合理的默认值填充，但 platform 和 action 必须明确。"""

		user_prompt = f"请解析以下指令：{instruction}"

		async with httpx.AsyncClient(timeout=30) as client:
			response = await client.post(
				f"{self._llm_base_url}/chat/completions",
				headers={
					"Authorization": f"Bearer {self._llm_api_key}",
					"Content-Type": "application/json",
				},
				json={
					"model": self._llm_model,
					"messages": [
						{"role": "system", "content": system_prompt},
						{"role": "user", "content": user_prompt},
					],
					"temperature": 0,
					"response_format": {"type": "json_object"},
				},
			)
			response.raise_for_status()

		data = response.json()
		content = data["choices"][0]["message"]["content"]

		try:
			result = json.loads(content)
		except json.JSONDecodeError:
			# Try to extract JSON from markdown code block
			m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
			if m:
				result = json.loads(m.group(1))
			else:
				raise ValueError(f"LLM returned non-JSON response: {content}")

		# Normalize platform name
		if "platform" in result:
			resolved = self._resolve_platform(result["platform"])
			if resolved:
				result["platform"] = resolved

		# Ensure required keys exist
		for key in ("platform", "action", "target", "params"):
			if key not in result:
				raise ValueError(f"LLM response missing required key: {key}")

		return result

	@staticmethod
	def _resolve_platform(name: str) -> str | None:
		"""Resolve a platform name/alias to its canonical form.

		Returns the canonical platform name, or None if unrecognized.
		"""
		normalized = name.strip().lower()
		return PLATFORM_ALIASES.get(normalized)
