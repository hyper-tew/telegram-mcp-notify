# Telegram `sendMessage` HTTP Template

## Bot message capabilities (Telegram Bot API)

Use this quick map when selecting a method:

- 📝 Text: `sendMessage`
- 🖼️ Photo: `sendPhoto`
- 🎞️ Video: `sendVideo`
- 🧾 Document/File: `sendDocument`
- 🎵 Audio track: `sendAudio`
- 🎙️ Voice note: `sendVoice`
- 🎬 Animation/GIF: `sendAnimation`
- 🧩 Sticker: `sendSticker`
- 🗂️ Album (2-10 media items): `sendMediaGroup`
- 📍 Location: `sendLocation`
- 🏢 Venue: `sendVenue`
- 👤 Contact: `sendContact`
- 🎲 Dice: `sendDice`
- 📊 Poll: `sendPoll` (close with `stopPoll`)
- 🔁 Copy/forward existing messages: `copyMessage`, `copyMessages`, `forwardMessage`, `forwardMessages`
- ✏️ Edit sent messages: `editMessageText`, `editMessageCaption`, `editMessageMedia`, `editMessageReplyMarkup`
- 🗑️ Delete messages: `deleteMessage`
- 📌 Pin/unpin messages: `pinChatMessage`, `unpinChatMessage`
- 👍 React to messages: `setMessageReaction`

For checkpoint notifications, default to 📝 `sendMessage` unless the prompt explicitly requests another type.

## Input schema

Required fields:

- `bot_token`: Telegram bot token string
- `chat_id`: target chat ID or `@channelusername`
- `text`: message text (1-4096 characters after entity parsing)

Optional fields:

- `parse_mode`: `HTML` or `MarkdownV2`
- `disable_notification`: boolean
- `reply_markup`: JSON object
- `message_thread_id`: integer

## Deterministic generation steps

1. Validate required fields exist.
2. Select method from the capability map (default: `sendMessage`).
3. Build endpoint as:
   - `https://api.telegram.org/bot<bot_token>/<selected_method>`
4. Set HTTP method:
   - `POST`
5. Set headers:
   - `Content-Type: application/json`
6. Build JSON body with required fields first:
   - `chat_id`, `text`
7. Add optional fields only when provided.
8. Redact `bot_token` in all displayed outputs.
9. Provide retry guidance for rate-limit responses.

## Output template

Use this structure in agent responses:

```text
Endpoint:
https://api.telegram.org/bot<redacted-token>/<selected_method>

Method:
POST

Headers:
Content-Type: application/json

JSON body:
{ ... }
```

### cURL example

```bash
curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "'"${TELEGRAM_CHAT_ID}"'",
    "text": "FINAL | build-task | Deployment complete",
    "disable_notification": false
  }'
```

### PowerShell example

```powershell
$uri = "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/sendMessage"
$body = @{
  chat_id = $env:TELEGRAM_CHAT_ID
  text = "FINAL | build-task | Deployment complete"
  disable_notification = $false
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri $uri -ContentType "application/json" -Body $body
```

## Expected response snippets

Success:

```json
{
  "ok": true,
  "result": {
    "message_id": 100
  }
}
```

Failure:

```json
{
  "ok": false,
  "error_code": 429,
  "description": "Too Many Requests: retry after 15",
  "parameters": {
    "retry_after": 15
  }
}
```

## Error-handling reminder

- If `parameters.retry_after` exists: wait and retry.
- If `parameters.migrate_to_chat_id` exists: update `chat_id` and resend.
- Always include final `error_code` and `description` when reporting failures.
