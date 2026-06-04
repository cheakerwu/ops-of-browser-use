"""Feishu approval workflow integration for task execution approval."""

from __future__ import annotations

import asyncio
import json
import logging

import lark_oapi as lark
from lark_oapi.api.approval.v4 import (
	CreateInstanceRequest,
	GetInstanceRequest,
	InstanceCreate,
)

from feishu_browser_use.task.models import Task

logger = logging.getLogger(__name__)


class FeishuApproval:
	"""Manages Feishu approval instances for browser automation tasks."""

	def __init__(self, client: lark.Client, approval_code: str | None = None) -> None:
		self._client = client
		self._approval_code = approval_code

	async def create_approval_instance(self, task: Task, screenshots: list[str] = []) -> str:
		"""Create an approval instance for a task and return the instance_id.

		Args:
			task: The Task model containing task details.
			screenshots: List of screenshot file keys or URLs.

		Returns:
			The approval instance ID string.

		Raises:
			RuntimeError: If the approval code is not configured or the API call fails.
		"""
		if not self._approval_code:
			raise RuntimeError("approval_code is not configured")

		form = self.build_approval_form(task, screenshots)

		body = (
			InstanceCreate.builder()
			.approval_code(self._approval_code)
			.open_id(task.user_id)
			.form(json.dumps(form, ensure_ascii=False))
			.build()
		)

		request = CreateInstanceRequest.builder().request_body(body).build()

		response = await asyncio.to_thread(
			self._client.approval.v4.instance.create, request
		)

		if not response.success():
			raise RuntimeError(
				f"Failed to create approval instance: code={response.code}, msg={response.msg}"
			)

		instance_id: str = response.data.instance_id
		logger.info("Created approval instance %s for task %s", instance_id, task.id)
		return instance_id

	async def get_approval_status(self, instance_id: str) -> str:
		"""Check the current status of an approval instance.

		Returns one of: PENDING, APPROVED, REJECTED, CANCELED.

		Raises:
			RuntimeError: If the API call fails.
		"""
		request = GetInstanceRequest.builder().instance_id(instance_id).build()

		response = await asyncio.to_thread(
			self._client.approval.v4.instance.get, request
		)

		if not response.success():
			raise RuntimeError(
				f"Failed to get approval status: code={response.code}, msg={response.msg}"
			)

		status: str = response.data.status or "UNKNOWN"
		return status.upper()

	async def wait_for_approval(
		self,
		instance_id: str,
		timeout_seconds: int = 3600,
		poll_interval: int = 30,
	) -> str:
		"""Poll the approval instance until it is resolved or timeout is reached.

		Args:
			instance_id: The approval instance ID to poll.
			timeout_seconds: Maximum seconds to wait before raising TimeoutError.
			poll_interval: Seconds between each poll attempt.

		Returns:
			The final status string (APPROVED, REJECTED, or CANCELED).

		Raises:
			TimeoutError: If the approval is not resolved within timeout_seconds.
			RuntimeError: If the API call fails.
		"""
		elapsed = 0

		while elapsed < timeout_seconds:
			status = await self.get_approval_status(instance_id)
			if status != "PENDING":
				logger.info("Approval instance %s resolved with status %s", instance_id, status)
				return status

			await asyncio.sleep(poll_interval)
			elapsed += poll_interval

		raise TimeoutError(
			f"Approval instance {instance_id} not resolved after {timeout_seconds}s"
		)

	def build_approval_form(self, task: Task, screenshots: list[str]) -> dict:
		"""Build the approval form content from task details.

		Args:
			task: The Task model containing task details.
			screenshots: List of screenshot file keys or URLs.

		Returns:
			A dict representing the approval form fields.
		"""
		form_fields = {
			"task_id": task.id,
			"description": task.instruction,
			"platform": task.platform,
			"product_details": task.instruction,
			"proposed_changes": f"Automated browser task on {task.platform}: {task.instruction}",
			"screenshots": screenshots,
		}

		return form_fields
