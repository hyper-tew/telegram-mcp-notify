---
name: telegram-notify
description: >
  Send Telegram notifications and collect user input via the telegram_notify MCP server.
  Use when sending checkpoint notifications, asking binary/MCQ questions, or managing
  listener lifecycle and pending prompt consumption.
triggers:
  - telegram notification
  - send notification
  - notify user
  - ask user via telegram
  - telegram input
  - telegram question
  - telegram confirmation
  - telegram choice
  - telegram listener
  - pending prompt
---

# Telegram Notify Skill (Minimal Core)

Manage Telegram notifications and bidirectional user input through the `telegram_notify` MCP server.

## Runtime Capability Gate (Mandatory)

Before claiming input/listener mode, verify available tools in runtime.

- Preferred preflight: `telegram_notify_capabilities`.
- Notify-only minimum: `send_telegram_notification`.
- Input minimum: one of `ask_user_confirmation` or `ask_user_choice`, plus `check_pending_prompt`.
- Lifecycle minimum:
  - `telegram_listener_health`
  - `start_telegram_listener`
  - `stop_telegram_listener`
  - `restart_telegram_listener`

If only notify tools are available:
- Explicitly state `notify-only mode`.
- Do not claim listener polling or reply consumption.

## MCP-Tool-First Policy (Mandatory)

When Telegram MCP tools are available, use MCP tools directly.

- Do not bypass MCP with local Python or direct Telegram HTTP calls.
- Non-MCP fallback is allowed only when capabilities are missing or MCP startup fails.
- On fallback, state failure reason and remediation path.

## Required Tool Surface (10 Tools)

The expected `telegram_notify` MCP surface is:

1. `send_telegram_notification`
2. `ask_user_confirmation`
3. `ask_user_choice`
4. `check_pending_prompt`
5. `wait_pending_prompt`
6. `telegram_listener_health`
7. `start_telegram_listener`
8. `stop_telegram_listener`
9. `restart_telegram_listener`
10. `telegram_notify_capabilities`

If fewer are exposed, treat runtime as degraded and report missing capabilities.

## Helper Message Rules (Mandatory)

One-line helper text must match real capabilities.

- Good (input mode): `Using telegram-notify in input mode (confirmation/choice + pending prompt checks available).`
- Good (notify-only): `Using telegram-notify in notify-only mode (reply-listener tools are unavailable in this runtime).`
- Bad: claiming free-form Telegram questioning or listener control when unavailable.

## Plan Mode Question Routing (Mandatory)

When Plan Mode needs user input:

1. Preflight with `telegram_notify_capabilities`.
2. Route by decision type:
   - Binary: `ask_user_confirmation`
   - 3+ options: `ask_user_choice`
   - Free-form: use in-UI `request_user_input` (no `ask_user` tool in minimal-core)
3. Use `timeout_minutes=5` for Telegram prompts.
4. Wait deterministically:
   - `wait_pending_prompt(session_id, prompt_id, timeout_seconds=300, consume=true)`
   - then `check_pending_prompt(session_id, prompt_id, consume=true)` once
5. On failure or timeout:
   - Emit one explicit warning in chat and fall back to one in-UI question.

## Checkpoint Notification Policy

Use `send_telegram_notification` at meaningful checkpoints:

- `event=question`: before a direct user question
- `event=plan_ready`: before presenting a plan
- `event=attention_needed`: when blocked on user action
- `event=error`: when a critical error occurs
- `event=final`: when task is completed

Do not notify routine progress chatter.

## Tool Reference

### Notification Tool

#### `send_telegram_notification`
Send structured notification payloads.

Required:
- `event`
- `message`

Optional:
- `task_name`
- `session_id`
- `run_id`
- `requires_action`

### Input Tools

#### `ask_user_confirmation`
Send a Yes/No question via inline keyboard.
- Listener accepts natural fallback text (`yes`, `y`, `approve`, `approved`, `no`, `n`, `decline`, `reject`), with optional 3-digit ref alias.

Required:
- `question`
- `session_id`

Optional:
- `task_name`
- `run_id`
- `timeout_minutes`
- `db_path`

#### `ask_user_choice`
Send a multiple-choice question.
- `allow_custom_text=true` (default): adds an `Other` button and accepts typed custom follow-up text.
- When `allow_custom_text=true`, mode is forced to inline (even for >4 choices).
- When `allow_custom_text=false`, auto mode uses inline for <=4 and poll for >4.

Required:
- `question`
- `choices`
- `session_id`

Optional:
- `task_name`
- `run_id`
- `input_mode`
- `allow_custom_text`
- `custom_choice_label`
- `timeout_minutes`
- `db_path`

#### `check_pending_prompt`
Fetch prompt state and optionally consume resolved responses.

Required:
- `session_id`
- `prompt_id`

Optional:
- `consume`
- `db_path`

#### `wait_pending_prompt`
Block until prompt leaves `waiting` or timeout expires.

Required:
- `session_id`
- `prompt_id`

Optional:
- `timeout_seconds`
- `poll_interval_seconds`
- `consume`
- `db_path`

### Lifecycle Tools

#### `telegram_listener_health`
Read listener diagnostics and recommended action.

#### `start_telegram_listener`
Start listener if not running.

#### `stop_telegram_listener`
Stop listener and reset runtime state.

#### `restart_telegram_listener`
Deterministic stop/start with health confirmation.

### Diagnostic Tool

#### `telegram_notify_capabilities`
Return runtime tool names, categories, and support flags.

## Input Workflow

1. Send question:
   - Binary: `ask_user_confirmation(...)`
   - MCQ: `ask_user_choice(...)`
2. Wait:
   - `wait_pending_prompt(..., consume=true)`
3. Confirm final state once:
   - `check_pending_prompt(..., consume=true)`
4. If still unresolved:
   - check `telegram_listener_health`
   - run `restart_telegram_listener` if unhealthy
   - retry prompt once after restart

## Conflict Handling

If prompt stays `waiting` and health shows `token_conflict`:

- Another process is polling `getUpdates` with the same token.
- Stop competing consumers on all machines using that token.
- Prefer dedicated bot tokens per environment/client.
