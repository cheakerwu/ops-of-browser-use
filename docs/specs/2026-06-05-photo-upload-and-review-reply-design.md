# 需求设计文档：图片上传 + 差评自动回复

> 日期：2026-06-05
> 状态：待审核
> 方案：A（扩展现有任务系统）

---

## 1. 背景与目标

### 1.1 背景

当前系统支持通过飞书消息发送文字指令，由 browser-use Agent 操控浏览器完成商家后台操作。但存在两个场景无法覆盖：

- **图片操作**：商户需要更换商品图片（主图、详情图），但系统无法接收和处理图片
- **差评回复**：商户需要手动逐条回复差评，耗时且容易遗漏

### 1.2 目标

| 功能 | 目标 | 成功标准 |
|------|------|---------|
| 图片上传 | 用户在飞书发送图片 + 文字指令，bot 自动将图片上传到商家后台 | 图片出现在目标商品页面 |
| 差评自动回复 | 支持手动触发和定时监控两种模式，LLM + 模板生成回复 | 差评被回复，回复内容合理 |

---

## 2. 功能 1：飞书图片上传

### 2.1 用户交互流程

**场景：更换商品主图**

```
用户（飞书）：
  [图片] + "朝阳店 美团 把咖啡主图换成这张"

Bot 回复：
  🔄 任务 abc12345 开始执行...
  （Agent 操作浏览器上传图片）
  ✅ 任务完成！📸 截图证据
```

**场景：多张图片**

```
用户（飞书）：
  [图片1] [图片2] [图片3] + "朝阳店 美团 更新商品详情图"

Bot 回复：
  🔄 收到 3 张图片，开始执行...
```

### 2.2 数据流

```
飞书 image 消息
    ↓
server.py: _handle_message_event()
    ├─ 检测 msg_type == "image"
    ├─ 提取 image_key
    ├─ 调用 feishu_bot.download_image(image_key) → 本地文件路径
    └─ 创建 Task(image_paths=[...], instruction=文字部分)
    ↓
Task Queue → Task Executor
    ├─ 把 image_paths 传给 Agent 的 task prompt
    └─ Agent 操作商家后台：找到上传入口 → 选择本地文件 → 上传
```

### 2.3 技术设计

#### 2.3.1 FeishuBot 新增方法

```python
async def download_image(self, image_key: str, save_dir: str) -> str | None:
    """从飞书下载图片到本地目录，返回文件路径。

    Args:
        image_key: 飞书图片 key
        save_dir: 保存目录

    Returns:
        本地文件路径，失败返回 None
    """
    # 使用 lark_oapi.api.im.v1.GetMessageResourceRequest
    # 或直接调用 HTTP API: GET /im/v1/images/{image_key}
```

#### 2.3.2 Task 模型扩展

```python
class Task(BaseModel):
    # ... 现有字段 ...
    image_paths: list[str] = Field(default_factory=list)  # 关联的本地图片路径
```

#### 2.3.3 server.py 消息处理扩展

```python
async def _handle_message_event(event: dict) -> None:
    msg_type = message.get("message_type", "")

    if msg_type == "text":
        # 现有逻辑
        ...

    elif msg_type == "image":
        # 新增：处理图片消息
        image_key = json.loads(message["content"]).get("image_key")
        local_path = await _feishu_bot.download_image(image_key, config.TEMP_DIR)
        # 等待后续文字指令，或直接解析图片消息中的文字
        ...

    elif msg_type == "post":
        # 新增：处理富文本消息（图片 + 文字混排）
        # 从 post.content 中提取所有 image_key 和 text
        ...
```

#### 2.3.4 Agent Prompt 增强

当 Task 包含图片时，在 prompt 中注入图片路径：

```python
def build_task_prompt(self, instruction: str, params: dict) -> str:
    parts = [f"平台：{self.PLATFORM_NAME}"]

    image_paths = params.get("image_paths", [])
    if image_paths:
        parts.append(f"已准备的图片文件：")
        for i, path in enumerate(image_paths, 1):
            parts.append(f"  图片{i}: {path}")
        parts.append(f"请将这些图片上传到对应位置。")

    parts.append(f"具体指令：{instruction}")
    return "\n".join(parts)
```

### 2.4 关键问题

| 问题 | 解决方案 |
|------|---------|
| 飞书图片下载需要权限 | 确保应用有 `im:resource` 权限 |
| 图片格式不支持 | 下载后检查格式，必要时用 Pillow 转换 |
| 多张图片顺序 | 按消息中出现顺序排列 |
| 图片临时文件清理 | 任务完成后在 finally 块中清理 |
| Agent 如何选择本地文件 | 使用 Playwright 的 `setInputFiles` API |

---

## 3. 功能 2：差评自动回复

### 3.1 用户交互流程

**手动触发：**

```
用户（飞书）：朝阳店 美团 回复差评

Bot 回复：
  🔄 正在检查差评...
  📋 发现 3 条新差评：
  1. ⭐ "送餐太慢了" - 2026-06-05
  2. ⭐⭐ "菜品和图片不一样" - 2026-06-05
  3. ⭐ "汤洒了" - 2026-06-04

  🤖 正在生成回复...
  ✅ 已回复 3 条差评
```

**定时自动模式：**

```
配置：每 30 分钟检查一次，直接发送

Bot 静默执行 → 发现差评 → 生成回复 → 直接发送到后台
→ 在飞书通知：📊 已自动回复 2 条差评（朝阳店 美团）
```

**定时 + 审核模式：**

```
Bot 发现差评 → 生成回复 → 发飞书审核卡片：

  📋 差评回复审核（朝阳店 美团）
  ━━━━━━━━━━━━━━━━━━
  差评："送餐太慢了" ⭐
  回复："非常抱歉给您带来不好的体验..."
  [✅ 确认发送] [✏️ 修改] [❌ 跳过]
```

### 3.2 数据流

```
手动模式：
  用户指令 → Task(type=REVIEW_REPLY) → Executor → Agent 登录后台 → 查差评 → 回复

定时模式：
  APScheduler 定时触发 → 检查各账号 → 发现新差评 → 生成回复
    ├─ 直接发送模式 → Agent 回复 → 飞书通知结果
    └─ 审核模式 → 飞书卡片 → 用户确认 → Agent 回复
```

### 3.3 技术设计

#### 3.3.1 定时调度器

```python
# feishu_browser_use/scheduler.py

from apscheduler.schedulers.asyncio import AsyncIOScheduler

class ReviewScheduler:
    """定时差评检查调度器。"""

    def __init__(self, executor: TaskExecutor, queue: TaskQueue, bot: FeishuBot):
        self._scheduler = AsyncIOScheduler()
        self._executor = executor
        self._queue = queue
        self._bot = bot

    def start(self, interval_minutes: int = 30):
        """启动定时任务。"""
        self._scheduler.add_job(
            self._check_all_accounts,
            'interval',
            minutes=interval_minutes,
            id='review_check'
        )
        self._scheduler.start()

    async def _check_all_accounts(self):
        """检查所有活跃账号的差评。"""
        accounts = await self._account_manager.get_all_accounts()
        for account in accounts:
            if account.status == AccountStatus.ACTIVE:
                task = Task(
                    user_id="scheduler",
                    chat_id=account.notify_chat_id,
                    platform=account.platform,
                    instruction="检查并回复差评",
                    account_id=account.id,
                    task_type="review_reply",
                )
                await self._queue.submit(task)
```

#### 3.3.2 差评回复生成器

```python
# feishu_browser_use/review_reply.py

class ReviewReplyGenerator:
    """模板 + LLM 生成差评回复。"""

    TEMPLATES = {
        "meituan": {
            "slow_delivery": "非常抱歉让您久等了！我们会优化配送流程，确保下次为您提供更快的服务。",
            "food_quality": "感谢您的反馈，我们会认真改进菜品质量，欢迎您再次光临。",
            "wrong_order": "非常抱歉给您带来困扰，我们会加强出餐核对，确保订单准确。",
            "default": "感谢您的宝贵意见，我们会认真改进，期待您的再次光临！",
        },
        "douyin": { ... },
        "taobao": { ... },
    }

    async def generate(self, platform: str, review_text: str, rating: int, llm) -> str:
        """生成差评回复。

        1. 匹配模板类别
        2. 用 LLM 在模板基础上个性化
        """
        template = self._match_template(platform, review_text, rating)

        prompt = f"""你是一个商家客服，请根据以下差评内容和回复模板，生成一条个性化的回复。

差评内容：{review_text}
评分：{rating}星
回复模板：{template}

要求：
1. 保持礼貌和专业
2. 针对差评内容做出具体回应
3. 表达改进意愿
4. 控制在 100 字以内
5. 不要使用模板的原话，在模板基础上自然改写"""

        return await llm.ainvoke(prompt)
```

#### 3.3.3 Platform Adapter 扩展

```python
# platforms/base.py - 新增抽象方法

class PlatformAdapter(ABC):
    # ... 现有方法 ...

    @abstractmethod
    async def get_reviews(self, browser_session) -> list[dict]:
        """获取待回复的差评列表。

        Returns:
            [{"id": "...", "text": "...", "rating": 1, "date": "...", "replied": False}]
        """

    @abstractmethod
    async def reply_to_review(self, browser_session, review_id: str, reply_text: str) -> bool:
        """回复指定差评。"""
```

```python
# platforms/meituan.py - 实现

class MeituanAdapter(PlatformAdapter):
    async def get_reviews(self, browser_session) -> list[dict]:
        """美团差评获取流程：
        1. 导航到评价管理页面
        2. 筛选差评（1-2星）
        3. 提取评价内容、日期、是否已回复
        """
        # Agent prompt 引导操作
        ...

    async def reply_to_review(self, browser_session, review_id: str, reply_text: str) -> bool:
        """美团差评回复流程：
        1. 找到对应评价
        2. 点击回复按钮
        3. 输入回复内容
        4. 提交
        """
        ...
```

#### 3.3.4 审核卡片

```python
# feishu/bot.py - 新增

def build_review_approval_card(self, reviews: list[dict], replies: list[str]) -> dict:
    """构建差评审核卡片。"""
    card = {
        "header": {"title": {"content": "📋 差评回复审核"}, "template": "orange"},
        "elements": []
    }

    for i, (review, reply) in enumerate(zip(reviews, replies)):
        card["elements"].append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**差评{i+1}：** {review['text']} ⭐" * review['rating']}
        })
        card["elements"].append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**回复：** {reply}"}
        })
        card["elements"].append({
            "tag": "action",
            "actions": [
                {"tag": "button", "text": {"content": "✅ 确认"}, "value": {"action": "review_approve", "review_id": review['id']}},
                {"tag": "button", "text": {"content": "❌ 跳过"}, "value": {"action": "review_skip", "review_id": review['id']}},
            ]
        })
        card["elements"].append({"tag": "hr"})

    return card
```

#### 3.3.5 配置扩展

```python
# config.py - 新增

class Settings(BaseModel):
    # ... 现有字段 ...

    # 差评回复配置
    REVIEW_CHECK_INTERVAL: int = 30  # 检查间隔（分钟）
    REVIEW_AUTO_REPLY: bool = False  # True=直接发送, False=需审核
    REVIEW_REPLY_ENABLED: bool = True  # 是否启用差评回复
    REVIEW_RATING_THRESHOLD: int = 2  # 几星以下算差评
```

---

## 4. 需要修改的文件清单

| 文件 | 修改内容 | 影响范围 |
|------|---------|---------|
| `task/models.py` | Task 新增 `image_paths`, `task_type` 字段 | 低 - 向后兼容 |
| `task/queue.py` | INSERT/SELECT SQL 适配新字段 | 低 - 自动迁移 |
| `task/executor.py` | 支持图片上下文传递、差评回复模式 | 中 |
| `feishu/bot.py` | 新增 `download_image()`, `build_review_approval_card()` | 低 - 新增方法 |
| `server.py` | 处理 image 消息、差评审核回调 | 中 |
| `platforms/base.py` | 新增 `get_reviews()`, `reply_to_review()` 抽象方法 | 低 - 新增接口 |
| `platforms/meituan.py` | 实现差评获取和回复 | 中 |
| `platforms/douyin.py` | 实现差评获取和回复 | 中 |
| `platforms/taobao.py` | 实现差评获取和回复 | 中 |
| `config.py` | 新增差评回复配置项 | 低 |
| `scheduler.py` | **新建** - 定时调度器 | 低 - 独立模块 |
| `review_reply.py` | **新建** - 回复生成器 | 低 - 独立模块 |

---

## 5. 依赖新增

| 包 | 用途 |
|----|------|
| `APScheduler` | 定时任务调度 |
| `Pillow` | 图片格式转换（已有） |

---

## 6. 实现优先级

```
Phase 1（基础）：
  ├─ Task 模型扩展（image_paths, task_type）
  ├─ FeishuBot.download_image()
  ├─ server.py 图片消息处理
  └─ Agent prompt 图片路径注入

Phase 2（差评回复 - 手动）：
  ├─ PlatformAdapter 新增 get_reviews(), reply_to_review()
  ├─ MeituanAdapter 实现
  ├─ ReviewReplyGenerator（模板 + LLM）
  └─ 手动触发指令 "回复差评"

Phase 3（差评回复 - 自动）：
  ├─ ReviewScheduler 定时调度
  ├─ 审核卡片
  ├─ 配置项
  └─ Douyin/Taobao 适配器实现
```

---

## 7. 风险与限制

| 风险 | 说明 | 缓解措施 |
|------|------|---------|
| 商家后台页面结构变化 | DOM 变化导致 Agent 找不到元素 | 定期更新 platform adapter 的 prompt |
| 差评回复内容不当 | LLM 生成的回复可能不合适 | 模板约束 + 审核模式 |
| 图片格式不支持 | 商家后台可能只接受特定格式 | 下载后检查并转换 |
| 定时任务资源消耗 | 每 30 分钟启动浏览器检查 | 控制并发数，复用 profile |
| 飞书 API 限流 | 频繁下载图片可能触发限流 | 加入速率限制 |

---

## 8. 测试策略

| 场景 | 测试方法 |
|------|---------|
| 图片消息接收 | 发送图片到飞书，验证下载成功 |
| 图片上传到后台 | 使用测试账号上传图片，验证页面显示 |
| 手动差评回复 | 发送指令，验证回复内容 |
| 定时差评检查 | 配置短间隔，验证定时触发 |
| 审核模式 | 发送差评卡片，验证按钮回调 |
| 多平台 | 分别测试美团/抖音/淘宝 |
