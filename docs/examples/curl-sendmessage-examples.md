# cURL `sendMessage` Examples

All examples use environment variables:

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
export TELEGRAM_CHAT_ID="123456789"
```

## Minimal plain text notification

```bash
curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "'"${TELEGRAM_CHAT_ID}"'",
    "text": "FINAL | ci-run | All checks passed"
  }'
```

## HTML parse mode example

```bash
curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "'"${TELEGRAM_CHAT_ID}"'",
    "text": "<b>PLAN READY</b> | release-task | Ready for review",
    "parse_mode": "HTML"
  }'
```

## MarkdownV2 parse mode example

```bash
curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "'"${TELEGRAM_CHAT_ID}"'",
    "text": "QUESTION \\| release\\-task \\| Approve deploy\\?",
    "parse_mode": "MarkdownV2"
  }'
```

## Silent notification example

```bash
curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "'"${TELEGRAM_CHAT_ID}"'",
    "text": "PLAN READY | docs-refresh | Ready to continue",
    "disable_notification": true
  }'
```

## Inline keyboard example

```bash
curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "'"${TELEGRAM_CHAT_ID}"'",
    "text": "QUESTION | deploy-gate | Select action",
    "reply_markup": {
      "inline_keyboard": [
        [
          { "text": "Approve", "callback_data": "approve" },
          { "text": "Reject", "callback_data": "reject" }
        ]
      ]
    }
  }'
```

## Common failure response example

```json
{
  "ok": false,
  "error_code": 429,
  "description": "Too Many Requests: retry after 20",
  "parameters": {
    "retry_after": 20
  }
}
```

Handling:

1. Sleep for `retry_after` seconds.
2. Retry with same payload.
3. If still failing, surface `error_code` and `description`.
