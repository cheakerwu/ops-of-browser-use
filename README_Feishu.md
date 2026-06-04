# Feishu Browser Use

基于 [browser-use](https://github.com/browser-use/browser-use) 的飞书 Bot 驱动浏览器自动化系统，面向美团/抖音/淘宝商家后台运营场景。

## 功能特性

### 核心能力

- **自然语言驱动**：通过飞书消息发送指令，AI 自动操作浏览器完成任务
- **多平台支持**：美团外卖商家后台、抖店商家后台、淘宝/千牛商家后台
- **多账号隔离**：每个账号独立的浏览器 Profile，登录态持久化
- **并发控制**：全局信号量限制并发数，同账号任务串行执行
- **执行证据**：任务完成时自动截图并发送到飞书，作为操作留证

### 账号管理

- 通过飞书交互卡片可视化管理账号
- 支持登录、删除、刷新状态等操作
- 登录态自动检测，失效时通知用户重新登录

### 任务控制

- 任务取消：取消运行中的任务
- 任务重试：失败/完成的任务一键重试
- 任务历史：查看最近的任务执行记录
- 运行状态：实时查看当前运行中的任务

### 飞书交互

- 交互卡片：账号管理、任务状态展示
- 按钮操作：取消、重试、登录、删除
- 图片消息：执行截图证据自动发送

## 架构

```
飞书消息 → Webhook → FastAPI Server
                         ↓
                    消息解析（平台/账号/指令）
                         ↓
                    任务队列（SQLite）
                         ↓
                    并发池（Semaphore + Lock）
                         ↓
                    TaskExecutor
                         ↓
                    browser-use Agent（LLM + CDP）
                         ↓
                    浏览器操作 → 截图 → 飞书通知
```

## 环境要求

- Python >= 3.11
- Chrome/Chromium 浏览器
- 飞书开放平台应用（需要 Bot 能力）
- LLM API（OpenAI 兼容格式）

## Windows 部署步骤

### 1. 安装 Python

```powershell
# 推荐使用 Anaconda 或 Miniconda
# 下载地址: https://docs.conda.io/en/latest/miniconda.html

# 或者从 python.org 安装 Python 3.11+
# 下载地址: https://www.python.org/downloads/
```

### 2. 克隆项目

```powershell
git clone <your-repo-url>
cd browser-use-main
```

### 3. 创建虚拟环境

```powershell
# 使用 conda
conda create -n feishu-browser python=3.11 -y
conda activate feishu-browser

# 或使用 venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 4. 安装依赖

```powershell
pip install -e .
pip install aiosqlite lark-oapi fastapi uvicorn
```

### 5. 配置环境变量

创建 `.env` 文件：

```env
# LLM 配置
LLM_MODEL=gpt-4o
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-api-key

# 飞书应用配置
FEISHU_APP_ID=your-app-id
FEISHU_APP_SECRET=your-app-secret

# 服务器配置
SERVER_PORT=8000
BROWSER_HEADLESS=true
MAX_CONCURRENT_TASKS=3

# 可选
# PROFILES_DIR=C:\Users\YourName\.feishu-browser-use\profiles
# TASK_DB_PATH=tasks.db
```

### 6. 启动 ngrok（开发环境）

```powershell
# 下载 ngrok: https://ngrok.com/download
ngrok http 8000
```

### 7. 配置飞书应用

1. 登录 [飞书开放平台](https://open.feishu.cn/)
2. 创建应用，开启机器人能力
3. 在「事件订阅」中添加回调地址：`https://your-ngrok-url/feishu/webhook`
4. 订阅事件：`im.message.receive_v1`、`card.action.trigger`
5. 在「权限管理」中开通：`im:message`、`im:message.create_v1`、`im:resource`
6. 发布应用版本

### 8. 启动服务

```powershell
python -m uvicorn feishu_browser_use.server:app --host 0.0.0.0 --port 8000
```

## macOS 部署步骤

### 1. 安装 Python

```bash
# 使用 Homebrew
brew install python@3.11

# 或使用 Anaconda
brew install --cask anaconda
```

### 2. 克隆项目

```bash
git clone <your-repo-url>
cd browser-use-main
```

### 3. 创建虚拟环境

```bash
# 使用 conda
conda create -n feishu-browser python=3.11 -y
conda activate feishu-browser

# 或使用 venv
python3 -m venv .venv
source .venv/bin/activate
```

### 4. 安装依赖

```bash
pip install -e .
pip install aiosqlite lark-oapi fastapi uvicorn
```

### 5. 配置环境变量

```bash
# 创建 .env 文件（同 Windows 步骤 5）
cp .env.example .env
# 编辑 .env 填入你的配置
```

### 6. 启动 ngrok

```bash
# 使用 Homebrew 安装
brew install ngrok
ngrok http 8000
```

### 7. 配置飞书应用

同 Windows 步骤 7。

### 8. 启动服务

```bash
python -m uvicorn feishu_browser_use.server:app --host 0.0.0.0 --port 8000
```

## 飞书 Bot 命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `<账号> <平台> <指令>` | 执行任务 | `朝阳店 美团 把咖啡价格改成25` |
| `账号列表` | 查看所有账号（卡片） | `账号列表` |
| `登录 <平台> <账号名>` | 登录账号 | `登录 美团 朝阳店` |
| `取消` | 取消所有运行中任务 | `取消` |
| `取消 <任务ID>` | 取消指定任务 | `取消 abc12345` |
| `运行中` | 查看运行中的任务 | `运行中` |
| `历史` | 查看最近任务记录 | `历史` |
| `帮助` | 查看使用帮助 | `帮助` |

## 项目结构

```
feishu_browser_use/
├── server.py              # FastAPI 服务器 + Webhook 处理
├── config.py              # 配置管理
├── account/
│   ├── models.py          # 账号数据模型
│   └── manager.py         # 账号管理（SQLite）
├── task/
│   ├── models.py          # 任务数据模型
│   ├── queue.py           # 任务队列（SQLite + asyncio.Queue）
│   ├── pool.py            # 并发执行池（Semaphore + Lock）
│   └── executor.py        # 任务执行器（browser-use Agent）
├── feishu/
│   ├── bot.py             # 飞书 Bot（消息/卡片/图片）
│   ├── client.py          # 飞书 SDK 客户端
│   └── approval.py        # 审批流程（预留）
└── platforms/
    ├── base.py            # 平台适配器基类
    ├── meituan.py         # 美团适配器
    ├── douyin.py           # 抖音适配器
    └── taobao.py          # 淘宝适配器
```

## 配置说明

| 环境变量 | 必填 | 默认值 | 说明 |
|---------|------|--------|------|
| `LLM_MODEL` | 是 | - | LLM 模型名称 |
| `LLM_BASE_URL` | 是 | - | LLM API 地址 |
| `LLM_API_KEY` | 是 | - | LLM API 密钥 |
| `FEISHU_APP_ID` | 是 | - | 飞书应用 ID |
| `FEISHU_APP_SECRET` | 是 | - | 飞书应用密钥 |
| `SERVER_PORT` | 否 | 8000 | 服务端口 |
| `BROWSER_HEADLESS` | 否 | true | 无头模式 |
| `MAX_CONCURRENT_TASKS` | 否 | 3 | 最大并发任务数 |
| `PROFILES_DIR` | 否 | ~/.feishu-browser-use/profiles | 浏览器 Profile 目录 |
| `TASK_DB_PATH` | 否 | tasks.db | SQLite 数据库路径 |

## 注意事项

1. **首次登录**：必须先通过 `登录 <平台> <账号名>` 命令在服务器上完成一次手动登录，后续任务才能复用登录态
2. **headless 模式**：生产环境建议 `BROWSER_HEADLESS=true`，调试时可设为 `false`
3. **ngrok 免费版**：每次重启会更换 URL，需要更新飞书应用的回调地址
4. **LLM 费用**：每个任务会多次调用 LLM，注意 API 用量
5. **并发限制**：`MAX_CONCURRENT_TASKS` 根据服务器内存和 CPU 调整
