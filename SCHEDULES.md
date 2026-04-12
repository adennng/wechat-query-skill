# OpenClaw 定时任务配置说明

时区统一使用 `Asia/Shanghai`。

## 任务一：每日 18:00 文章推送

**配置命令：**

```bash
openclaw cron add \
  --agent <YOUR_AGENT_ID> \
  --name "wechat-query-daily-push" \
  --cron "0 18 * * *" \
  --tz "Asia/Shanghai" \
  --message "进行今日文章推送。进入 wechat-query skill。先向用户发送一条简短说明，告知将开始预检并整理发布时间在最近 24 小时内的文章。然后按 SKILL.md 执行每日18:00文章推送场景。" \
  --session isolated \
  --to "chat:<YOUR_FEISHU_CHAT_ID>"
```

**任务说明：**
- 触发时间：每日北京时间 18:00
- 触发方式：cron 表达式 `0 18 * * *`
- 执行内容：推送最近 24 小时发布的公众号文章
- 执行智能体：由 `--agent` 参数指定

---

## 任务二：每日 09:00 服务与登录巡检

**配置命令：**

```bash
openclaw cron add \
  --agent <YOUR_AGENT_ID> \
  --name "wechat-query-daily-inspection" \
  --cron "0 9 * * *" \
  --tz "Asia/Shanghai" \
  --message "进行服务与登录巡检。进入 wechat-query skill。先向用户发送简短说明，告知将开始巡检。然后按 SKILL.md 执行每日09:00巡检场景：Linux/macOS 运行 scripts/check_service_and_login.sh，Windows 运行 scripts/check_service_and_login.ps1，并根据返回结果通知用户。" \
  --session isolated \
  --to "chat:<YOUR_FEISHU_CHAT_ID>"
```

**任务说明：**
- 触发时间：每日北京时间 09:00
- 触发方式：cron 表达式 `0 9 * * *`
- 执行内容：巡检 wechat-download-api 服务状态和微信登录状态
- 执行智能体：由 `--agent` 参数指定
- 脚本选择：
  - Linux / macOS：`scripts/check_service_and_login.sh`
  - Windows：`scripts/check_service_and_login.ps1`

---

## 任务列表

| 任务名称 | 调度表达式 | 时区 | 用途 | 执行智能体 |
|---------|-----------|------|------|-----------|
| wechat-query-daily-push | `0 18 * * *` | Asia/Shanghai | 每日文章推送 | `<YOUR_AGENT_ID>` |
| wechat-query-daily-inspection | `0 9 * * *` | Asia/Shanghai | 服务与登录巡检 | `<YOUR_AGENT_ID>` |

---

## 定时任务与智能体的关联机制

### 1. `--agent` 参数绑定

定时任务通过 `--agent <YOUR_AGENT_ID>` 参数与智能体绑定。这意味着：
- 任务触发时，OpenClaw 会启动目标智能体的一个新会话
- 任务在该智能体的上下文中执行
- 任务可以访问该智能体工作空间下的所有文件（SKILL.md、scripts/、services/ 等）

### 2. 会话隔离

`--session isolated` 参数确保：
- 定时任务在独立的会话中执行
- 不会干扰用户的正常对话会话
- 任务完成后会话自动清理

### 3. 消息触发机制

`--message` 参数的内容会在任务触发时发送给智能体，作为用户请求：
- 智能体收到消息后，按 AGENTS.md 和 SKILL.md 的指引执行


### 4. 工作空间继承

目标智能体应配置到当前 skill 目录，例如：
```json
{
  "id": "<YOUR_AGENT_ID>",
  "workspace": "<PATH_TO_THIS_SKILL_DIR>"
}
```

### 5. 验证命令

查看已创建的定时任务：
```bash
openclaw cron list
```

输出中的 `Agent` 列显示任务绑定的智能体：
```
wechat-query-daily-push       ...  <YOUR_AGENT_ID>
wechat-query-daily-inspection ...  <YOUR_AGENT_ID>
```

---
