from abc import ABC, abstractmethod


class PlatformAdapter(ABC):
	"""Abstract base class for platform-specific adapters.

	Each platform (e.g. Feishu, DingTalk, WeCom) implements this interface
	to provide platform-specific system prompts and task prompt construction.
	"""

	PLATFORM_NAME: str
	LOGIN_URL: str

	@abstractmethod
	def get_prepare_system_prompt(self, instruction: str) -> str:
		"""Return the system prompt used during the prepare phase.

		Args:
			instruction: The high-level task instruction from the user.

		Returns:
			A system prompt string that guides the LLM through the
			preparation steps (login, navigation, environment setup).
		"""

	@abstractmethod
	def get_execute_system_prompt(self, instruction: str) -> str:
		"""Return the system prompt used during the execute phase.

		Args:
			instruction: The high-level task instruction from the user.

		Returns:
			A system prompt string that guides the LLM through the
			actual task execution after preparation is complete.
		"""

	@abstractmethod
	def build_task_prompt(self, instruction: str, params: dict) -> str:
		"""Build the full agent task prompt combining instruction and parameters.

		Args:
			instruction: The high-level task instruction from the user.
			params: Platform-specific parameters (e.g. document IDs,
				recipient lists, message content).

		Returns:
			A complete prompt string ready to be passed to the browser
			agent for execution.
		"""
