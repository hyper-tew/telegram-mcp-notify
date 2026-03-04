# Event Notification Prompt Templates

Use these snippets when asking an agent to formulate Telegram Bot API HTTP requests.

## Shared prompt frame

```text
Formulate a Telegram Bot API HTTP request for sendMessage.
Return:
1) endpoint (redacted token)
2) method
3) headers
4) json body
5) curl command
6) powershell Invoke-RestMethod command
7) success/failure response interpretation

Inputs:
- bot_token: <redacted or env var reference>
- chat_id: <chat id>
- event: <event name>
- task_name: <task>
- summary: <short summary>
- details: <optional list>
- parse_mode: <optional HTML or MarkdownV2>
- disable_notification: <optional true/false>
```

## Event-specific snippets

### `question`

```text
event=question
message first line: ❓ QUESTION | <task_name> | <summary>
Use concise wording and include exactly one requested decision in details.
```

### `plan_ready`

```text
event=plan_ready
message first line: 🧭 PLAN READY | <task_name> | <summary>
Include high-level scope and expected next action.
```

### `final`

```text
event=final
message first line: ✅ FINAL | <task_name> | <summary>
Include completion status and validation result in details.
```

### `attention_needed`

```text
event=attention_needed
message first line: 🚨 ATTENTION | <task_name> | <summary>
Include blocking reason and immediate action required.
```

### `error`

```text
event=error
message first line: ❌ ERROR | <task_name> | <summary>
Include failing step, observed error, and retry/mitigation guidance.
```

## Message-type capability tags (use when needed)

Add one capability emoji when the message content references a specific Telegram method:

- 📝 `sendMessage` (text notifications)
- 🖼️ `sendPhoto`
- 🎞️ `sendVideo`
- 🧾 `sendDocument`
- 🎵 `sendAudio`
- 🎙️ `sendVoice`
- 🎬 `sendAnimation`
- 📊 `sendPoll`
- 📍 `sendLocation`

Example:

```text
✅ FINAL 📝 | release-task | Notification sent
```

## Message variants

Compact variant:

```text
EMOJI EVENT | task-name | summary
```

Detailed variant:

```text
EMOJI EVENT | task-name | summary
- detail line 1
- detail line 2
- detail line 3
```

## Parse mode guidance

- Use `parse_mode=HTML` when structured tags are needed and HTML escaping is controlled.
- Use `parse_mode=MarkdownV2` only when escaping rules are correctly applied.
- If uncertain, omit `parse_mode` and send plain text.
