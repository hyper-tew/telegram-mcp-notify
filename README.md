# telegram-mcp-notify

Telegram notification MCP server with bidirectional reply support for AI coding agents (Cursor, Codex, Claude Code).

## Features

- **Outbound notifications**: Send structured Telegram messages for questions, plans, errors, final results, and attention-needed events.
- **Inbound replies**: Receive user responses via text commands, inline keyboards, or polls.
- **High-level input tools**: `ask_user`, `ask_user_confirmation`, `ask_user_choice` for simplified user interaction.
- **Singleton lifecycle**: File-based locking ensures only one server/listener runs at a time.
- **Self-healing listener**: Automatic stale PID/lock cleanup and restart.
- **Cross-platform**: Works on Windows (msvcrt) and POSIX (fcntl).

## Prerequisites

- **Python 3.11+**
- **Telegram bot token** -- create one via [@BotFather](https://t.me/BotFather)
- **Telegram chat ID** -- send any message to your bot, then open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and look for `"chat":{"id": ...}`

## Installation

```bash
# From GitHub
pip install git+https://github.com/hyper-tew/telegram-mcp-notify.git

# From a local clone
pip install ./telegram-mcp-notify

# Development (editable + test deps)
pip install -e "./telegram-mcp-notify[dev]"
```

After installation the `telegram-mcp-notify` command is available on your `PATH`.

## Setup -- Cursor

Create or edit the MCP configuration file and put your Telegram credentials in the `env` block.

**Project-level** -- `.cursor/mcp.json` in your project root (applies to that project only):

```json
{
  "mcpServers": {
    "telegram_notify": {
      "command": "telegram-mcp-notify",
      "args": [],
      "env": {
        "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF...",
        "TELEGRAM_CHAT_ID": "123456789"
      }
    }
  }
}
```

**Global** -- `~/.cursor/mcp.json` (applies to all projects):

Same JSON structure as above.

> **Note:** Restart Cursor after editing the MCP configuration for changes to take effect.

## Setup -- Codex

Add the server to your Codex `config.toml` with credentials in the `[mcp_servers.telegram_notify.env]` table.

**Global** -- `~/.codex/config.toml`:

```toml
[mcp_servers.telegram_notify]
command = "telegram-mcp-notify"
args = []

[mcp_servers.telegram_notify.env]
TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."
TELEGRAM_CHAT_ID = "123456789"
```

**Project-scoped** -- `.codex/config.toml` in your project root (trusted projects only). Same TOML structure as above.

**CLI shortcut** -- you can also add the server from the terminal:

```bash
codex mcp add telegram_notify \
  --env TELEGRAM_BOT_TOKEN=123456:ABC-DEF... \
  --env TELEGRAM_CHAT_ID=123456789 \
  -- telegram-mcp-notify
```

## Optional Configuration

You can pass additional environment variables in the same `env` block alongside the required ones.

**Cursor** (inside the `"env"` object):

```json
{
  "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF...",
  "TELEGRAM_CHAT_ID": "123456789",
  "TELEGRAM_PARSE_MODE": "HTML",
  "TELEGRAM_TIMEOUT_SECONDS": "15"
}
```

**Codex** (under `[mcp_servers.telegram_notify.env]`):

```toml
[mcp_servers.telegram_notify.env]
TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."
TELEGRAM_CHAT_ID = "123456789"
TELEGRAM_PARSE_MODE = "HTML"
TELEGRAM_TIMEOUT_SECONDS = "15"
```

See the full list of variables in the [Environment Variables](#environment-variables) table below.

## Available Tools

### Notification Tools

| Tool | Description |
|------|-------------|
| `send_telegram_notification` | Send structured notification (event, message, task_name) |

### High-Level Input Tools

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

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| No notifications received | Bot token or chat ID wrong | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` |
| Prompt stays "waiting" | Listener not running | Call `start_telegram_listener` or `repair_telegram_listener` |
| "stale_lock" health reason | Previous listener crashed | Call `repair_telegram_listener(restart=true)` |
| "heartbeat_stale" | Listener froze or network issue | Call `repair_telegram_listener(restart=true)` |
| Prompt expired | User didn't respond in time | Increase `timeout_minutes` or re-ask |
| Inline button not responding | Callback not matched | Ensure listener is running via `telegram_listener_health` |

## Data Paths

All data defaults to `~/.telegram-mcp-notify/`:
- `inbox.db` -- SQLite inbox database
- `listener.log` -- Listener log file
- `locks/` -- Singleton lock files

Override with environment variables: `TELEGRAM_INBOX_DB_PATH`, `TELEGRAM_LISTENER_LOG_PATH`, `TELEGRAM_SINGLETON_LOCK_DIR`.

## License

MIT
