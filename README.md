# telegram-mcp-notify

Telegram notification MCP server with bidirectional reply support for AI coding agents (Cursor, Codex, Claude Code).

## Features

- **Outbound notifications**: Send structured Telegram messages for questions, plans, errors, final results, and attention-needed events.
- **Inbound replies**: Receive user responses via text commands, inline keyboards, or polls.
- **High-level input tools**: `ask_user`, `ask_user_confirmation`, `ask_user_choice` for simplified user interaction.
- **Singleton lifecycle**: File-based locking ensures only one server/listener runs at a time.
- **Self-healing listener**: Automatic stale PID/lock cleanup and restart.
- **Cross-platform**: Works on Windows (msvcrt) and POSIX (fcntl).

## Installation

```bash
# From local clone
pip install ./telegram-mcp-notify

# From git
pip install git+https://github.com/USER/telegram-mcp-notify.git

# Development
pip install -e "./telegram-mcp-notify[dev]"
```

## Setup

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather) and get the bot token.
2. Get your chat ID (send a message to the bot, then check `https://api.telegram.org/bot<TOKEN>/getUpdates`).
3. Set environment variables:

```bash
export TELEGRAM_BOT_TOKEN="your-bot-token"
export TELEGRAM_CHAT_ID="your-chat-id"
```

## MCP Configuration

### Cursor (`.mcp.json` or `.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "telegram_notify": {
      "command": "telegram-mcp-notify",
      "args": []
    }
  }
}
```

### Codex (`~/.codex/config.toml`)

```toml
[mcp_servers.telegram_notify]
command = "telegram-mcp-notify"
args = []
```

## Available Tools

### Notification Tools

| Tool | Description |
|------|-------------|
| `send_telegram_notification` | Send structured notification (event, message, task_name) |

### High-Level Input Tools (New)

| Tool | Description |
|------|-------------|
| `ask_user` | Send a text question and register for reply |
| `ask_user_confirmation` | Yes/No inline keyboard |
| `ask_user_choice` | Multiple-choice via poll or inline keyboard |
| `cancel_prompt` | Cancel a pending prompt |
| `get_recent_messages` | Retrieve recent inbound messages |

### Low-Level Input Tools

| Tool | Description |
|------|-------------|
| `register_pending_prompt` | Register prompt with text/poll/inline delivery |
| `check_pending_prompt` | Check status and consume resolved response |
| `list_pending_prompts` | List prompts by session with status filter |

### Lifecycle Tools

| Tool | Description |
|------|-------------|
| `telegram_listener_health` | Listener health diagnostics |
| `start_telegram_listener` | Start the reply listener daemon |
| `repair_telegram_listener` | Repair stale PID/lock and optionally restart |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | - | Bot API token |
| `TELEGRAM_CHAT_ID` | Yes | - | Trusted chat ID |
| `TELEGRAM_PARSE_MODE` | No | None | Message parse mode (HTML/Markdown) |
| `TELEGRAM_DISABLE_NOTIFICATION` | No | false | Suppress all notifications |
| `TELEGRAM_TIMEOUT_SECONDS` | No | 10 | HTTP request timeout |
| `TELEGRAM_INBOX_DB_PATH` | No | `~/.telegram-mcp-notify/inbox.db` | SQLite inbox path |
| `TELEGRAM_LISTENER_LOG_PATH` | No | `~/.telegram-mcp-notify/listener.log` | Listener log path |
| `TELEGRAM_SINGLETON_LOCK_DIR` | No | `~/.telegram-mcp-notify/locks/` | Lock file directory |

## License

MIT
