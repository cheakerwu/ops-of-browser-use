"""Feishu Docs integration (placeholder for future implementation)."""

import lark_oapi as lark


class FeishuDocs:
	"""Placeholder for Feishu Docs API operations.

	TODO: Implement actual Feishu Docs API calls using lark.Client.
	See https://open.feishu.cn/document/server-docs/docs/docs-overview for API reference.
	"""

	def __init__(self, client: lark.Client) -> None:
		self._client = client

	async def create_doc(self, title: str, content: str) -> str:
		"""Create a new Feishu document.

		Args:
			title: Document title.
			content: Initial document content.

		Returns:
			doc_token of the newly created document.
		"""
		raise NotImplementedError(
			"FeishuDocs.create_doc is a placeholder. "
			"Implement using lark_oapi Document API."
		)

	async def update_doc(self, doc_token: str, content: str) -> None:
		"""Update the content of an existing Feishu document.

		Args:
			doc_token: Token identifying the document to update.
			content: New document content.
		"""
		raise NotImplementedError(
			"FeishuDocs.update_doc is a placeholder. "
			"Implement using lark_oapi Document API."
		)

	async def upload_image(self, file_path: str) -> str:
		"""Upload an image to Feishu.

		Args:
			file_path: Local path to the image file.

		Returns:
			image_key for the uploaded image.
		"""
		raise NotImplementedError(
			"FeishuDocs.upload_image is a placeholder. "
			"Implement using lark_oapi Drive/Media API."
		)
