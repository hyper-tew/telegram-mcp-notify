---
name: telegram-notify
description: >
  Send Telegram notifications via the telegram_notify MCP server in notify-only mode.
  Use for question/plan/final checkpoints and critical manual-attention alerts.
triggers:
  - telegram notification
  - send notification
  - notify user
  - notify-only
  - checkpoint notification
---

# Telegram Notify Skill (Notify-Only)

Use the `telegram_notify` MCP server for outbound notifications only.

## Runtime Capability Gate (Mandatory)

- Preferred preflight: `telegram_notify_capabilities`.
- Required minimum tools:
  - `send_telegram_notification`
  - `telegram_notify_capabilities`
- Do not use or claim Telegram input/listener workflows in this mode.

## Notification Policy (Mandatory)

Use `send_telegram_notification` only at meaningful checkpoints:

- `event=question`: before a direct user question
- `event=plan_ready`: before presenting a plan
- `event=final`: when task is completed
- `event=error`: only when manual user attention is required
- `event=attention_needed`: only when manual user attention is required

Do not notify routine progress chatter.

## MCP-Tool-First Policy (Mandatory)

When Telegram MCP tools are available, use MCP tools directly.

- Do not bypass MCP with local Python or direct Telegram HTTP calls.
- If MCP is unavailable, state the failure reason and continue in-chat.

## Tool Reference

### `send_telegram_notification`

Required:
- `event`
- `message`

Optional:
- `task_name`
- `session_id`
- `run_id`
- `requires_action`

### `telegram_notify_capabilities`

Use this to verify runtime capability before claiming notify behavior.
