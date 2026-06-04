"""Douyin (TikTok) merchant backend platform adapter."""

from __future__ import annotations

from feishu_browser_use.platforms.base import PlatformAdapter


class DouyinAdapter(PlatformAdapter):
	"""Douyin (抖店) merchant backend adapter for price management tasks.

	Handles the two-phase workflow:
	1. Prepare: navigate to the product, change the price, screenshot the change
	2. Execute: submit the price change and confirm
	"""

	PLATFORM_NAME = "douyin"
	LOGIN_URL = "https://fxg.jinritemai.com/"

	def get_prepare_system_prompt(self, instruction: str) -> str:
		"""Return the prepare-phase system prompt for Douyin price changes.

		Guides the agent through: login verification -> product navigation ->
		price modification -> screenshot capture, WITHOUT clicking save/submit.
		"""
		return f"""你是一个抖店（抖音电商）商家后台的自动化操作助手。

你的任务是准备一次商品价格修改操作。请严格按照以下步骤执行：

## 步骤 1：确认登录状态
- 当前页面应为抖店商家后台（https://fxg.jinritemai.com/）
- 如果页面显示登录界面，请停下来并报告需要登录，不要尝试自动登录
- 如果已登录，继续下一步

## 步骤 2：导航到商品管理
- 找到左侧菜单栏中的「商品」或「商品管理」选项并点击
- 在子菜单中选择「商品列表」或「商品管理」选项
- 等待商品列表页面加载完成

## 步骤 3：找到目标商品
- 根据指令中的商品名称，在商品列表中搜索或浏览找到目标商品
- 如果有搜索框，可以使用搜索功能快速定位
- 找到商品后，点击该商品的「编辑」按钮或商品名称进入编辑页面

## 步骤 4：修改价格
- 在商品编辑页面中，找到价格相关的输入字段（通常标记为「价格」、「售价」或「原价」）
- 清除当前价格值
- 输入目标价格值：{instruction}
- 确认价格已正确填入输入框

## 步骤 5：截图确认
- 在完成价格修改后，对当前页面进行截图
- 截图应清晰显示修改后的价格字段
- 这张截图将作为操作凭证

## 重要注意事项
- **绝对不要**点击「保存」、「提交」、「发布」或任何类似的提交按钮
- **绝对不要**离开当前编辑页面
- 如果遇到任何弹窗提示，请关闭它但不要确认提交
- 每一步操作后都要等待页面响应，确保操作生效
- 如果某个元素找不到，尝试滚动页面或等待页面完全加载
- 使用中文与页面上的元素进行交互

## 当前任务指令
{instruction}
"""

	def get_execute_system_prompt(self, instruction: str) -> str:
		"""Return the execute-phase system prompt for Douyin price changes.

		Guides the agent through: verify prepared state -> click save/submit ->
		confirm the change -> screenshot the result.
		"""
		return f"""你是一个抖店（抖音电商）商家后台的自动化操作助手。

你的任务是执行一次商品价格修改的提交操作。准备阶段已完成价格的修改，现在需要提交保存。

请严格按照以下步骤执行：

## 步骤 1：确认当前状态
- 当前页面应处于商品编辑页面，且价格字段已修改为目标值
- 确认页面上显示的价格确实是目标价格
- 如果页面不在预期状态，请停下来并报告问题

## 步骤 2：提交修改
- 找到页面上的「保存」、「提交」或「发布」按钮
- 该按钮通常位于页面底部或右上角
- 点击该按钮提交价格修改

## 步骤 3：处理确认弹窗
- 提交后可能会弹出确认对话框，询问是否确认修改
- 如果出现确认弹窗，点击「确定」或「确认」按钮
- 如果没有弹窗，继续下一步

## 步骤 4：验证提交结果
- 等待页面响应，确认修改已成功保存
- 查看是否有成功提示（如「保存成功」、「修改成功」、「发布成功」等）
- 如果出现错误提示，请记录错误信息并报告

## 步骤 5：截图记录
- 对提交结果页面进行截图
- 截图应显示成功保存的提示信息

## 重要注意事项
- 在点击提交按钮前，请再次确认价格值是正确的
- 如果提交失败，不要反复重试，记录错误信息即可
- 注意观察页面上的任何警告或错误提示
- 操作完成后不要离开当前页面

## 当前任务指令
{instruction}
"""

	def build_task_prompt(self, instruction: str, params: dict) -> str:
		"""Build the full task prompt for a Douyin price change operation.

		Args:
			instruction: The high-level price change instruction.
			params: May contain:
				- product_name (str): Name of the product to modify.
				- target_price (str | float): The new price to set.
				- phase (str): "prepare" or "execute".

		Returns:
			A complete prompt string for the browser agent.
		"""
		product_name = params.get("product_name", "")
		target_price = params.get("target_price", "")
		phase = params.get("phase", "prepare")

		parts = [f"平台：抖店商家后台"]

		if product_name:
			parts.append(f"目标商品：{product_name}")
		if target_price:
			parts.append(f"目标价格：{target_price}")

		parts.append(f"操作阶段：{'准备阶段（修改价格并截图，不提交）' if phase == 'prepare' else '执行阶段（提交保存并确认）'}")
		parts.append("")
		parts.append(f"具体指令：{instruction}")

		return "\n".join(parts)
