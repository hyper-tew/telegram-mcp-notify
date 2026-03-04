# telegram-mcp-notify (skill/prompt-only branch)

This branch is intentionally a docs-and-skill variant. It does not ship a runtime MCP server.

The goal is to help agents formulate correct Telegram Bot API HTTP requests for notification messages using prompt instructions and templates.

If you need the runnable Python MCP server, use `main`.

## Branch intent

- No Python package runtime in this branch
- One core skill: `telegram-notify`
- Prompt templates for deterministic request generation
- Reference docs and examples for `sendMessage`

## Source grounding

- Telegram Bot Features: <https://core.telegram.org/bots/features>
- Telegram Bot API: <https://core.telegram.org/bots/api>
- Context7 reference used for this branch: `/websites/core_telegram_bots_api`

## Quick start

1. Use `.agents/skills/telegram-notify/SKILL.md` as the agent behavior contract.
2. Reuse templates from `.agents/skills/telegram-notify/templates/`.
3. Generate outbound requests for `sendMessage` with required inputs:
   - `bot_token`
   - `chat_id`
   - `text`
4. Add optional request fields as needed:
   - `parse_mode`
   - `disable_notification`
   - `reply_markup`

## Request primer (`sendMessage`)

Canonical endpoint:

```text
https://api.telegram.org/bot<token>/sendMessage
```

Minimal JSON payload:

```json
{
  "chat_id": "123456789",
  "text": "Build finished: all checks passed."
}
```

### cURL example

```bash
curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "'"${TELEGRAM_CHAT_ID}"'",
    "text": "FINAL | release-task | Build finished",
    "disable_notification": false
  }'
```

### PowerShell example

```powershell
$uri = "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/sendMessage"
$body = @{
  chat_id = $env:TELEGRAM_CHAT_ID
  text = "FINAL | release-task | Build finished"
  disable_notification = $false
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri $uri -ContentType "application/json" -Body $body
```

## Environment variable guidance

Recommended local variables for examples:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_PARSE_MODE` (optional)
- `TELEGRAM_DISABLE_NOTIFICATION` (optional)

Never print full bot tokens in logs, docs, or chat messages.

## Event notification templates

| Event | Prefix | Typical intent |
|---|---|---|
| `question` | `QUESTION` | Ask for a decision or missing input |
| `plan_ready` | `PLAN READY` | Announce a completed plan |
| `final` | `FINAL` | Mark task completion |
| `attention_needed` | `ATTENTION` | Manual intervention required |
| `error` | `ERROR` | Failure summary and next action |

Example text format:

```text
EVENT | task-name | short summary
detail line 1
detail line 2
```

## Response handling checklist

Success shape:

```json
{
  "ok": true,
  "result": {
    "message_id": 123
  }
}
```

Failure shape:

```json
{
  "ok": false,
  "error_code": 429,
  "description": "Too Many Requests: retry after 10",
  "parameters": {
    "retry_after": 10
  }
}
```

If present:

- `parameters.retry_after`: wait then retry
- `parameters.migrate_to_chat_id`: resend to migrated chat ID

## Compatibility note

This branch is instruction-based only. It replaces runtime interfaces with skill and prompt artifacts.

For executable MCP behavior (`telegram_mcp_notify`, console script, server tools), switch to `main`.
