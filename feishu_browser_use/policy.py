"""Policy gate for user instructions before they reach the browser agent."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

PolicyStatus = Literal["allowed", "blocked", "needs_confirmation"]


class PolicyDecision(BaseModel):
	model_config = ConfigDict(extra="forbid")

	status: PolicyStatus
	intent: str
	reason: str
	allowed_domains: list[str] = Field(default_factory=list)
	blocked_domains: list[str] = Field(default_factory=list)


class PolicyGate:
	"""Allow only supported merchant-backend tasks into browser automation."""

	_ALLOWED_DOMAINS: dict[str, list[str]] = {
		"meituan": [
			"e.waimai.meituan.com",
			"waimaie.meituan.com",
			"epassport.meituan.com",
		],
		"eleme": [
			"shop.ele.me",
			"nr.ele.me",
		],
		"douyin": [
			"life.douyin.com",
		],
	}

	_INJECTION_PATTERNS = (
		"忽略之前",
		"忽略以上",
		"无视之前",
		"绕过",
		"泄露",
		"cookie",
		"token",
		"api key",
		"apikey",
		"本地文件",
		"系统提示",
		"system prompt",
		"developer message",
	)

	_HIGH_RISK_PATTERNS = (
		"改价",
		"价格",
		"下架",
		"上架",
		"删除",
		"上传",
		"覆盖",
		"发布",
		"提交",
		"保存",
	)

	def evaluate(self, raw_text: str, platform: str, instruction: str) -> PolicyDecision:
		"""Evaluate a parsed user task before agent execution."""
		intent = self._infer_intent(raw_text, instruction)
		allowed_domains = self._ALLOWED_DOMAINS.get(platform, [])

		if self._contains_injection_risk(raw_text):
			return PolicyDecision(
				status="blocked",
				intent=intent,
				reason="检测到越权或提示词注入风险",
				allowed_domains=allowed_domains,
			)

		url_domains = self._extract_url_domains(raw_text)
		blocked_domains = [
			domain for domain in url_domains
			if not self._domain_allowed(domain, allowed_domains)
		]
		if blocked_domains:
			return PolicyDecision(
				status="blocked",
				intent=intent,
				reason=f"不支持访问非白名单网站: {blocked_domains[0]}",
				allowed_domains=allowed_domains,
				blocked_domains=blocked_domains,
			)

		if not allowed_domains:
			return PolicyDecision(
				status="blocked",
				intent=intent,
				reason="暂不支持该平台",
			)

		# High-risk confirmation disabled - all operations allowed directly
		# if self._requires_confirmation(raw_text):
		#     return PolicyDecision(
		#         status="needs_confirmation",
		#         intent=intent,
		#         reason="高风险操作需要二次确认",
		#         allowed_domains=allowed_domains,
		#     )

		return PolicyDecision(
			status="allowed",
			intent=intent,
			reason="允许执行",
			allowed_domains=allowed_domains,
		)

	def _infer_intent(self, raw_text: str, instruction: str) -> str:
		text = f"{raw_text} {instruction}"
		if any(word in text for word in ("价格", "改价", "涨价", "降价")):
			return "change_price"
		if any(word in text for word in ("上传", "图片", "照片", "菜单图")):
			return "update_image"
		if any(word in text for word in ("登录", "重新登录")):
			return "login"
		if any(word in text for word in ("打开", "进入", "访问")):
			return "open_merchant_backend"
		return "general_task"

	def _contains_injection_risk(self, text: str) -> bool:
		normalized = text.lower()
		return any(pattern in normalized for pattern in self._INJECTION_PATTERNS)

	def _requires_confirmation(self, text: str) -> bool:
		return any(pattern in text for pattern in self._HIGH_RISK_PATTERNS)

	def _extract_url_domains(self, text: str) -> list[str]:
		domains: list[str] = []
		for match in re.finditer(r"https?://[^\s，。]+", text):
			parsed = urlparse(match.group(0))
			if parsed.hostname:
				domains.append(parsed.hostname.lower())
		return domains

	def _domain_allowed(self, domain: str, allowed_domains: list[str]) -> bool:
		return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in allowed_domains)
