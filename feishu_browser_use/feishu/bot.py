from __future__ import annotations

import json
import logging
from pathlib import Path

import lark_oapi as lark

logger = logging.getLogger(__name__)
from lark_oapi.api.im.v1 import (
	CreateImageRequest,
	CreateImageRequestBody,
	CreateMessageRequest,
	CreateMessageRequestBody,
	ReplyMessageRequest,
	ReplyMessageRequestBody,
)

from feishu_browser_use.task.models import Task, TaskStatus

# Status -> (display label, header color)
_STATUS_DISPLAY: dict[str, tuple[str, str]] = {
	TaskStatus.PENDING.value: ("Pending", "grey"),
	TaskStatus.PARSING.value: ("Parsing", "blue"),
	TaskStatus.PREPARING.value: ("Preparing", "blue"),
	TaskStatus.EXECUTING.value: ("Running", "blue"),
	TaskStatus.AWAITING_APPROVAL.value: ("Approval Needed", "orange"),
	TaskStatus.COMPLETED.value: ("Completed", "green"),
	TaskStatus.FAILED.value: ("Failed", "red"),
	TaskStatus.CANCELLED.value: ("Cancelled", "grey"),
}


class FeishuBot:
	"""Feishu bot that sends messages and interactive cards via the lark-oapi SDK."""

	def __init__(self, client: lark.Client) -> None:
		self._client = client

	async def send_text(self, chat_id: str, content: str) -> None:
		"""Send a plain text message to a chat."""
		body = (
			CreateMessageRequestBody.builder()
			.receive_id(chat_id)
			.msg_type("text")
			.content(json.dumps({"text": content}))
			.build()
		)
		request = (
			CreateMessageRequest.builder()
			.receive_id_type("chat_id")
			.request_body(body)
			.build()
		)
		response = await self._client.im.v1.message.acreate(request)
		if not response.success():
			raise RuntimeError(
				f"Failed to send text message: {response.code} {response.msg}"
			)

	async def send_card(self, chat_id: str, card: dict) -> None:
		"""Send an interactive card message to a chat."""
		body = (
			CreateMessageRequestBody.builder()
			.receive_id(chat_id)
			.msg_type("interactive")
			.content(json.dumps(card))
			.build()
		)
		request = (
			CreateMessageRequest.builder()
			.receive_id_type("chat_id")
			.request_body(body)
			.build()
		)
		response = await self._client.im.v1.message.acreate(request)
		if not response.success():
			raise RuntimeError(
				f"Failed to send card message: {response.code} {response.msg}"
			)

	async def reply_text(self, message_id: str, content: str) -> None:
		"""Reply to a specific message with plain text."""
		body = (
			ReplyMessageRequestBody.builder()
			.msg_type("text")
			.content(json.dumps({"text": content}))
			.build()
		)
		request = (
			ReplyMessageRequest.builder()
			.message_id(message_id)
			.request_body(body)
			.build()
		)
		response = await self._client.im.v1.message.areply(request)
		if not response.success():
			raise RuntimeError(
				f"Failed to reply to message: {response.code} {response.msg}"
			)

	async def reply_card(self, message_id: str, card: dict) -> None:
		"""Reply to a specific message with an interactive card."""
		body = (
			ReplyMessageRequestBody.builder()
			.msg_type("interactive")
			.content(json.dumps(card))
			.build()
		)
		request = (
			ReplyMessageRequest.builder()
			.message_id(message_id)
			.request_body(body)
			.build()
		)
		response = await self._client.im.v1.message.areply(request)
		if not response.success():
			raise RuntimeError(
				f"Failed to reply with card: {response.code} {response.msg}"
			)

	async def upload_image(self, image_path: str) -> str | None:
		"""Upload an image file to Feishu and return the image_key.

		Args:
			image_path: Path to the image file.

		Returns:
			image_key string on success, None on failure.
		"""
		try:
			image_data = Path(image_path).read_bytes()
			body = (
				CreateImageRequestBody.builder()
				.image_type("message")
				.image(image_data)
				.build()
			)
			request = CreateImageRequest.builder().request_body(body).build()
			response = await self._client.im.v1.image.acreate(request)
			if response.success() and response.data:
				return response.data.image_key
			logger.warning("Failed to upload image: %s %s", response.code, response.msg)
			return None
		except Exception:
			logger.warning("Failed to upload image", exc_info=True)
			return None

	async def send_image(self, chat_id: str, image_key: str) -> None:
		"""Send an image message to a chat using an uploaded image_key."""
		body = (
			CreateMessageRequestBody.builder()
			.receive_id(chat_id)
			.msg_type("image")
			.content(json.dumps({"image_key": image_key}))
			.build()
		)
		request = (
			CreateMessageRequest.builder()
			.receive_id_type("chat_id")
			.request_body(body)
			.build()
		)
		response = await self._client.im.v1.message.acreate(request)
		if not response.success():
			raise RuntimeError(
				f"Failed to send image: {response.code} {response.msg}"
			)

	def build_task_card(self, task: Task) -> dict:
		"""Build an interactive card displaying task status with color coding."""
		label, color = _STATUS_DISPLAY.get(
			task.status.value, ("Unknown", "grey")
		)

		created_at_str = task.created_at.strftime("%Y-%m-%d %H:%M:%S")

		# Header
		card: dict = {
			"config": {"wide_screen_mode": True},
			"header": {
				"title": {"tag": "plain_text", "content": f"Task [{task.id[:8]}]"},
				"template": color,
			},
			"elements": [],
		}

		elements: list[dict] = card["elements"]

		# Task info fields
		fields: list[dict] = [
			{
				"is_short": True,
				"text": {"tag": "lark_md", "content": f"**Task ID:**\n{task.id}"},
			},
			{
				"is_short": True,
				"text": {"tag": "lark_md", "content": f"**Platform:**\n{task.platform}"},
			},
			{
				"is_short": True,
				"text": {"tag": "lark_md", "content": f"**Status:**\n{label}"},
			},
			{
				"is_short": True,
				"text": {"tag": "lark_md", "content": f"**Created:**\n{created_at_str}"},
			},
		]
		elements.append({"tag": "div", "fields": fields})

		# Instruction block
		elements.append({"tag": "hr"})
		elements.append(
			{
				"tag": "div",
				"text": {
					"tag": "lark_md",
					"content": f"**Instruction:**\n{task.instruction}",
				},
			}
		)

		# Result / error block (if present)
		if task.result is not None:
			elements.append({"tag": "hr"})
			result_icon = "✅" if task.result.success else "❌"
			elements.append(
				{
					"tag": "div",
					"text": {
						"tag": "lark_md",
						"content": f"**Result:** {result_icon} {task.result.message}",
					},
				}
			)
		elif task.error is not None:
			elements.append({"tag": "hr"})
			elements.append(
				{
					"tag": "div",
					"text": {
						"tag": "lark_md",
						"content": f"**Error:**\n{task.error}",
					},
				}
			)

		# Action buttons based on current status
		elements.append({"tag": "hr"})
		actions: list[dict] = []

		if task.status in (
			TaskStatus.PENDING,
			TaskStatus.PARSING,
			TaskStatus.PREPARING,
			TaskStatus.EXECUTING,
		):
			actions.append(
				{
					"tag": "button",
					"text": {"tag": "plain_text", "content": "Cancel"},
					"type": "default",
					"value": {"action": "cancel", "task_id": task.id},
				}
			)

		if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
			actions.append(
				{
					"tag": "button",
					"text": {"tag": "plain_text", "content": "Retry"},
					"type": "primary",
					"value": {"action": "retry", "task_id": task.id},
				}
			)

		if actions:
			elements.append({"tag": "action", "actions": actions})

		return card

	async def send_task_card(self, chat_id: str, task: Task) -> None:
		"""Build and send a task card to the given chat."""
		card = self.build_task_card(task)
		await self.send_card(chat_id, card)

	async def send_task_update(self, task: Task) -> None:
		"""Send an updated task card to the task's originating chat."""
		card = self.build_task_card(task)
		await self.send_card(task.chat_id, card)

	def build_account_card(self, accounts: list) -> dict:
		"""Build an interactive card for account management.

		Args:
			accounts: List of Account objects to display.

		Returns:
			Feishu interactive card dict.
		"""
		from feishu_browser_use.account.models import AccountStatus

		_STATUS_ICON = {
			AccountStatus.ACTIVE.value: "🟢",
			AccountStatus.NEEDS_LOGIN.value: "🟡",
			AccountStatus.DISABLED.value: "🔴",
		}

		_PLATFORM_NAME = {
			"meituan": "美团",
			"douyin": "抖音",
			"taobao": "淘宝",
		}

		card: dict = {
			"config": {"wide_screen_mode": True},
			"header": {
				"title": {"tag": "plain_text", "content": "📋 账号管理"},
				"template": "blue",
			},
			"elements": [],
		}
		elements: list[dict] = card["elements"]

		if not accounts:
			elements.append({
				"tag": "div",
				"text": {
					"tag": "lark_md",
					"content": "暂无已配置的账号。\n点击下方按钮添加。",
				},
			})
		else:
			for account in accounts:
				icon = _STATUS_ICON.get(account.status.value, "⚪")
				platform_display = _PLATFORM_NAME.get(account.platform, account.platform)
				status_text = account.status.value

				# Last used time
				if account.last_used_at:
					from datetime import datetime
					delta = datetime.now() - account.last_used_at
					if delta.total_seconds() < 60:
						time_str = "刚刚"
					elif delta.total_seconds() < 3600:
						time_str = f"{int(delta.total_seconds() // 60)}分钟前"
					elif delta.total_seconds() < 86400:
						time_str = f"{int(delta.total_seconds() // 3600)}小时前"
					else:
						time_str = f"{int(delta.days)}天前"
				else:
					time_str = "从未使用"

				# Account info line
				info_line = f"{icon} **{account.name}** ({platform_display})　{status_text}　最后使用: {time_str}"

				elements.append({
					"tag": "div",
					"text": {"tag": "lark_md", "content": info_line},
				})

				# Action buttons per account
				elements.append({
					"tag": "action",
					"actions": [
						{
							"tag": "button",
							"text": {"tag": "plain_text", "content": "🔐 重新登录"},
							"type": "primary",
							"value": {
								"action": "account_login",
								"account_id": account.id,
								"platform": account.platform,
								"name": account.name,
							},
						},
						{
							"tag": "button",
							"text": {"tag": "plain_text", "content": "🗑️ 删除"},
							"type": "danger",
							"value": {
								"action": "account_delete",
								"account_id": account.id,
								"name": account.name,
							},
						},
					],
				})

				elements.append({"tag": "hr"})

		# Bottom action buttons
		elements.append({
			"tag": "action",
			"actions": [
				{
					"tag": "button",
					"text": {"tag": "plain_text", "content": "➕ 添加账号"},
					"type": "default",
					"value": {"action": "account_add"},
				},
				{
					"tag": "button",
					"text": {"tag": "plain_text", "content": "🔄 刷新状态"},
					"type": "default",
					"value": {"action": "account_refresh"},
				},
			],
		})

		return card
