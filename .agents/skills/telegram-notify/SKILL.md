---
name: telegram-notify
description: >
  Formulate Telegram Bot API HTTP requests for outbound notifications.
  Use this skill when an agent must produce deterministic `sendMessage` requests, including
  parse-mode handling, retry policy, and safe redaction of secrets.
triggers:
  - telegram bot api
  - sendmessage
  - formulate http request
  - telegram notification payload
  - telegram parse mode
---

# Telegram Notify Skill (HTTP Formulation)

Use this skill to generate Telegram Bot API requests. This branch does not provide MCP runtime tools.

## Inputs

Required:

- `bot_token`
- `chat_id`
- `text`

Optional:

- `parse_mode` (`HTML` or `MarkdownV2`)
- `disable_notification` (`true` or `false`)
- `reply_markup` (JSON object)
- `message_thread_id` (forum topic support)

## Canonical endpoint

```text
https://api.telegram.org/bot<token>/METHOD_NAME
```

Primary method for this skill:

- `sendMessage`

## Event mapping

Use these event labels in message text:

- `question`
- `plan_ready`
- `final`
- `attention_needed`
- `error`

Recommended first line format:

```text
EVENT | task-name | short summary
```

## Formatting rules

### HTML (`parse_mode=HTML`)

- Escape unsupported literal symbols:
  - `<` -> `&lt;`
  - `>` -> `&gt;`
  - `&` -> `&amp;`
  - `"` -> `&quot;`
- Use only supported Telegram HTML tags.

### MarkdownV2 (`parse_mode=MarkdownV2`)

Escape reserved characters with backslash in normal text:

```text
_ * [ ] ( ) ~ ` > # + - = | { } . !
```

Inside inline links, escape `)` and `\` where required.

## Failure handling policy

For any `ok=false` response:

1. Surface `error_code` and `description`.
2. If `parameters.retry_after` exists, wait that many seconds and retry.
3. If `parameters.migrate_to_chat_id` exists, update `chat_id` and resend.
4. Keep retries bounded and report final failure details.

## Output contract

When this skill is used, output must include:

1. Endpoint URL (token redacted)
2. HTTP method
3. Headers
4. JSON body
5. `curl` example
6. PowerShell `Invoke-RestMethod` example
7. Success and failure response interpretation

## Safety rules

- Never print full bot tokens. Show redacted form, for example: `123456:ABC...`.
- Redact secrets from logs and docs.
- Do not invent API fields. Use Telegram Bot API documented parameters.

## Template references

- `templates/send-message-http.md`
- `templates/event-notification-prompts.md`
