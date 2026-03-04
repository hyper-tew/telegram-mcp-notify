# Telegram Bot API HTTP Notifications Guide

This document defines how agents should formulate outbound notification requests with Telegram Bot API `sendMessage`.

## Official references

- Features overview: <https://core.telegram.org/bots/features>
- Bot API reference: <https://core.telegram.org/bots/api>
- Context7 library reference used in this repo: `/websites/core_telegram_bots_api`

## Request fundamentals

Base pattern:

```text
https://api.telegram.org/bot<token>/METHOD_NAME
```

For notifications, use:

```text
METHOD_NAME = sendMessage
```

Supported parameter transports:

- URL query string
- `application/x-www-form-urlencoded`
- `application/json` (recommended here)

## Required fields

- `chat_id`
- `text`

`text` must be 1-4096 characters after entity parsing.

## Optional fields commonly used for notifications

- `parse_mode`
- `disable_notification`
- `reply_markup`
- `message_thread_id`

## Parse mode rules

### HTML

If `parse_mode=HTML`, ensure literal symbols are escaped:

- `<` -> `&lt;`
- `>` -> `&gt;`
- `&` -> `&amp;`
- `"` -> `&quot;`

### MarkdownV2

Escape special characters where required:

```text
_ * [ ] ( ) ~ ` > # + - = | { } . !
```

If you cannot guarantee escaping correctness, send plain text.

## Event-to-message mapping

- `question`: `QUESTION | task-name | summary`
- `plan_ready`: `PLAN READY | task-name | summary`
- `final`: `FINAL | task-name | summary`
- `attention_needed`: `ATTENTION | task-name | summary`
- `error`: `ERROR | task-name | summary`

## Response interpretation

Success pattern:

```json
{
  "ok": true,
  "result": {
    "message_id": 123
  }
}
```

Failure pattern:

```json
{
  "ok": false,
  "error_code": 400,
  "description": "Bad Request: chat not found"
}
```

Special failure parameters:

- `parameters.retry_after`: wait and retry
- `parameters.migrate_to_chat_id`: update target `chat_id` and resend

## Safety and redaction

- Never expose full bot tokens in prompts, docs, or logs.
- Use environment variables in command examples.
- Redact secrets in diagnostics and response reports.

## Output contract for agent responses

When asked to formulate a Telegram request, include:

1. Endpoint URL (token redacted)
2. HTTP method
3. Headers
4. JSON payload
5. cURL command
6. PowerShell command
7. Success and failure response interpretation
