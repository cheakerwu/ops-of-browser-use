# Phase 2 Feishu Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve user-visible task progress in Feishu with task cards, task detail/log commands, and card update plumbing.

**Architecture:** Keep the existing FastAPI webhook and SQLite queue. Add task card message tracking to `Task`, let `FeishuBot` return/update card message IDs, and use `task_events` to power details/log/history commands.

**Tech Stack:** Python 3.13 in conda `ceshi`, FastAPI, lark-oapi, SQLite, pytest.

---

### Task 1: Persist Task Card Message ID

**Files:**
- Modify: `feishu_browser_use/task/models.py`
- Modify: `feishu_browser_use/task/queue.py`
- Test: `tests/test_task_card_updates.py`

- [ ] Write failing tests for persisting `task_card_message_id`.
- [ ] Add `task_card_message_id` to `Task`.
- [ ] Add SQLite migration and update serialization.
- [ ] Add `TaskQueue.set_task_card_message_id`.
- [ ] Run `conda run -n ceshi python -m pytest tests/test_task_card_updates.py`.

### Task 2: Feishu Card Create/Update APIs

**Files:**
- Modify: `feishu_browser_use/feishu/bot.py`
- Test: `tests/test_task_card_updates.py`

- [ ] Write tests for `reply_task_card` returning message ID and `update_task_card` calling SDK update.
- [ ] Implement card reply return value extraction.
- [ ] Implement update existing message with interactive card content.
- [ ] Run task card update tests.

### Task 3: Update Task Card on Status Changes

**Files:**
- Modify: `feishu_browser_use/server.py`
- Modify: `feishu_browser_use/task/executor.py`
- Test: `tests/test_executor_card_updates.py`

- [ ] Write tests for executor updating task card when status changes.
- [ ] Store card message ID after task creation.
- [ ] Update card at executing/completed/failed/cancelled.
- [ ] Run executor card tests.

### Task 4: Detail, Log, and History Commands

**Files:**
- Modify: `feishu_browser_use/server.py`
- Modify: `feishu_browser_use/feishu/bot.py`
- Test: `tests/test_task_detail_commands.py`

- [ ] Write tests for `详情 <task_id>`, `日志 <task_id>`, and existing `历史`.
- [ ] Build task detail card from task + events.
- [ ] Build task log text from `task_events`.
- [ ] Make history include task status and readable error fields.
- [ ] Run detail command tests.

### Task 5: Verify Phase 2

**Files:**
- All changed files.

- [ ] Run `conda run -n ceshi python -m pytest tests`.
- [ ] Restart uvicorn in conda `ceshi`.
- [ ] Verify local `/healthz`.
- [ ] Verify ngrok `/healthz`.
