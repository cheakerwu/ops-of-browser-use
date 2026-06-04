from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
	model_config = ConfigDict(
		env_file=".env",
		env_file_encoding="utf-8",
		extra="ignore",
	)

	# Feishu
	FEISHU_APP_ID: str | None = None
	FEISHU_APP_SECRET: str | None = None
	FEISHU_VERIFICATION_TOKEN: str | None = None
	FEISHU_ENCRYPT_KEY: str | None = None
	FEISHU_APPROVAL_CODE: str | None = None  # 飞书审批定义 code

	# LLM
	LLM_BASE_URL: str = "https://api.deepseek.com/v1"
	LLM_API_KEY: str
	LLM_MODEL: str = "deepseek-chat"

	# Platform: Meituan
	PLATFORM_MEITUAN_USERNAME: str | None = None
	PLATFORM_MEITUAN_PASSWORD: str | None = None

	# Platform: Douyin
	PLATFORM_DOUYIN_USERNAME: str | None = None
	PLATFORM_DOUYIN_PASSWORD: str | None = None

	# Platform: Taobao
	PLATFORM_TAOBAO_USERNAME: str | None = None
	PLATFORM_TAOBAO_PASSWORD: str | None = None

	# Task & Server
	TASK_DB_PATH: str = "tasks.db"
	SERVER_PORT: int = 8000

	# Browser
	BROWSER_HEADLESS: bool = True
	BROWSER_USER_DATA_DIR: str | None = None

	# Account profiles
	PROFILES_DIR: str | None = None  # 默认 ~/.feishu-browser-use/profiles
	MAX_CONCURRENT_TASKS: int = 3  # 最大并发任务数


_config: Settings | None = None


def get_config() -> Settings:
	global _config
	if _config is None:
		_config = Settings()
	return _config
