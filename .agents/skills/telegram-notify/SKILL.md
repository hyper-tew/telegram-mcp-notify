---
name: telegram-notify
description: >
  Send Telegram notifications and collect user input via the telegram_notify MCP server.
  Use when sending notifications at task checkpoints, asking users questions via Telegram,
  or managing the reply listener lifecycle.
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

# Telegram Notify Skill

Manage Telegram notifications and bidirectional user input through the `telegram_notify` MCP server.

## When to Use

Use Telegram notification tools at these checkpoints:

- **Direct questions** (`event=question`): Before any question where user input is needed.
- **Plan handoff** (`event=plan_ready`): Right before presenting a `<proposed_plan>` block.
- **Blocked on input** (`event=attention_needed`): When progress is blocked and user decision is required.
- **Errors** (`event=error`): When a critical error occurs that the user should know about.
- **Final completion** (`event=final`): After delivering the final answer for a task.

**Do NOT send notifications for:**
- Progress updates -- no `progress` event exists; do not notify routine progress
- Every turn of conversation
- Internal tool calls or status checks

## Notification Protocol (Mandatory)

1. Use compact message format:
   - Line 1: `{emoji} {EVENT} | {task name}`
   - Line 2: `{short summary}`
2. Match event types to situations:
   - `event=question` before any direct user question
   - `event=plan_ready` before emitting a `<proposed_plan>` block
   - `event=final` before final non-plan completion messages
   - `event=attention_needed` only when genuinely blocked
   - `event=error` for failures
   - **No progress events** -- do not send progress notifications
3. On send failure, retry once; if second attempt fails, note it in the response and continue.

## Tool Reference

### Notification Tool

#### `send_telegram_notification`
Send a structured notification to Telegram.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event` | string | yes | One of: `question`, `plan_ready`, `final`, `attention_needed`, `error` |
| `message` | string | yes | Notification body text |
| `task_name` | string | no | Task label (auto-inferred from env/message if omitted) |
| `session_id` | string | no | Session identifier |
| `run_id` | string | no | Run identifier |
| `requires_action` | bool | no | Adds ACTION REQUIRED banner |

### High-Level Input Tools

#### `ask_user`
Send a text question and register it as a pending prompt. Combines notification + prompt registration in one call.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `question` | string | yes | - | The question text |
| `session_id` | string | yes | - | Session identifier |
| `task_name` | string | no | auto | Task label |
| `run_id` | string | no | - | Run identifier |
| `timeout_minutes` | int | no | 5 | Prompt expiry |
| `db_path` | string | no | auto | Inbox DB path |

User replies via text: `ANSWER <prompt_id> <response>` or `APPROVE/DECLINE <prompt_id>`.

#### `ask_user_confirmation`
Send a Yes/No question via inline keyboard buttons.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `question` | string | yes | - | The confirmation question |
| `session_id` | string | yes | - | Session identifier |
| `timeout_minutes` | int | no | 5 | Prompt expiry |

Returns a prompt_id. Check result with `check_pending_prompt`.

#### `ask_user_choice`
Send a multiple-choice question. Auto-selects inline keyboard (<=4 choices) or poll (>4).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `question` | string | yes | - | The question |
| `choices` | list[str] | yes | - | At least 2 options |
| `session_id` | string | yes | - | Session identifier |
| `input_mode` | string | no | "auto" | Force "inline" or "poll", or "auto" |
| `timeout_minutes` | int | no | 5 | Prompt expiry |

#### `cancel_prompt`
Cancel a waiting prompt so it is no longer awaited.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | yes | Session identifier |
| `prompt_id` | string | yes | The prompt to cancel |

#### `get_recent_messages`
Retrieve recent inbound messages from the inbox database.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | int | no | 10 | Max messages to return |

### Low-Level Input Tools

#### `register_pending_prompt`
Register a prompt with full control over delivery mode (text/poll/inline).

Key parameters: `session_id`, `prompt_text`, `prompt_id`, `input_mode`, `choices`, `expires_in_minutes`, `send_notification`, `ensure_listener`.

#### `check_pending_prompt`
Check a prompt's status. Set `consume=true` to mark a resolved response as consumed.

Key parameters: `session_id`, `prompt_id`, `consume`.

Returns: `status`, `response_type`, `response_text`, `selected_option_ids`, `selected_options`.

#### `list_pending_prompts`
List prompts for a session with optional `status_filter` (waiting/resolved/consumed/expired/cancelled).

### Lifecycle Tools

#### `telegram_listener_health`
Returns listener diagnostics: running status, PID, heartbeat age, health reason, recommended action.

#### `start_telegram_listener`
Start the reply listener daemon if not running. Includes self-healing for stale state.

#### `repair_telegram_listener`
Clean up stale PID/lock state and optionally restart the listener.

## Input Workflow

To ask a user a question and get a response:

1. **Send the question:**
   ```
   ask_user(question="Should I proceed?", session_id="my-session")
   ```
   Returns `{ prompt_id, status: "waiting", ... }`

2. **Poll for the response:**
   ```
   check_pending_prompt(session_id="my-session", prompt_id="<id>", consume=true)
   ```
   If `status == "resolved"`, the `response_text` contains the user's answer.
   If `status == "waiting"`, try again after a short delay.
   If `status == "expired"`, the user did not respond in time.

3. **For confirmations:** Use `ask_user_confirmation` -- returns Yes/No via inline buttons.

4. **For multiple choice:** Use `ask_user_choice` -- auto-picks inline vs poll based on option count.
