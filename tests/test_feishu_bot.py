from types import SimpleNamespace

import pytest

from feishu_browser_use.feishu.bot import FeishuBot


class FakeImageApi:
	def __init__(self):
		self.image_body = None

	async def acreate(self, request):
		self.image_body = request.body
		image_value = self.image_body.image.read()
		assert image_value == b"png-bytes"
		return SimpleNamespace(
			success=lambda: True,
			data=SimpleNamespace(image_key="img-key"),
		)


@pytest.mark.asyncio
async def test_upload_image_sends_file_stream(tmp_path):
	image_path = tmp_path / "evidence.png"
	image_path.write_bytes(b"png-bytes")
	image_api = FakeImageApi()
	client = SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace(image=image_api)))

	image_key = await FeishuBot(client).upload_image(str(image_path))

	assert image_key == "img-key"
	assert image_api.image_body.image_type == "message"
