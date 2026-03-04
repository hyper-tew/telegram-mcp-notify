# telegram-mcp-notify

Notify-only Telegram MCP server for AI coding agents (Cursor, Codex, Claude Code).

## IMPORTANT DISCLAIMER (WIP / SELF-USE)

> [!WARNING]
> This repository is still in active development and currently intended for personal/self use and experimentation.
> APIs and behavior may change without notice.
> Use at your own risk.

## Breaking Changes in 0.2.0

- Removed console script: `telegram-mcp-listener`
- Removed reply/input internals (`inbox`, listener lifecycle, pending prompts)
- Removed singleton lock behavior for server startup

## Features

- Outbound Telegram notifications for:
  - `question`
  - `plan_ready`
  - `final`
  - `attention_needed`
  - `error`
- Notify-only MCP surface:
  - `send_telegram_notification`
  - `telegram_notify_capabilities`
- Cross-platform runtime (Windows and POSIX)

## Prerequisites

- Python 3.11+
- `uv` / `uvx` (recommended) or `pip`
- Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Telegram chat ID

## Quick Start: Cursor

Create `.cursor/mcp.json` in your project root (or `~/.cursor/mcp.json` globally):

```json
{
  "mcpServers": {
    "telegram_notify": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/hyper-tew/telegram-mcp-notify",
        "telegram-mcp-notify"
      ],
      "env": {
        "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF...",
        "TELEGRAM_CHAT_ID": "123456789"
      }
    }
  }
}
```

Restart Cursor after saving.

## Quick Start: Codex

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.telegram_notify]
command = "uvx"
args = ["--from", "git+https://github.com/hyper-tew/telegram-mcp-notify", "telegram-mcp-notify"]

[mcp_servers.telegram_notify.env]
TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."
TELEGRAM_CHAT_ID = "123456789"
```

Or via CLI:

```bash
codex mcp add telegram_notify \
  --env TELEGRAM_BOT_TOKEN=123456:ABC-DEF... \
  --env TELEGRAM_CHAT_ID=123456789 \
  -- uvx --from "git+https://github.com/hyper-tew/telegram-mcp-notify" telegram-mcp-notify
```

## Alternative: Pre-install with pip

```bash
# From GitHub
pip install git+https://github.com/hyper-tew/telegram-mcp-notify.git

# From local clone
pip install ./telegram-mcp-notify

# Development
pip install -e "./telegram-mcp-notify[dev]"
```

Then use Python module mode in MCP config:

```toml
[mcp_servers.telegram_notify]
command = "python"
args = ["-m", "telegram_mcp_notify.server"]

[mcp_servers.telegram_notify.env]
TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."
TELEGRAM_CHAT_ID = "123456789"
```

## Environment Variables

Required:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Optional:

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_PARSE_MODE` | None | Message parse mode (`HTML` or `Markdown`) |
| `TELEGRAM_DISABLE_NOTIFICATION` | `false` | Suppress outbound notifications |
| `TELEGRAM_TIMEOUT_SECONDS` | `10` | HTTP request timeout |

## Available Tools

| Tool | Description |
|---|---|
| `send_telegram_notification` | Send a structured Telegram checkpoint notification |
| `telegram_notify_capabilities` | Return current server tool/capability surface |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No notifications received | Invalid token/chat ID | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` |
| Unexpected tools shown | Running old package version | Upgrade/restart MCP runtime |
| `spawn telegram-mcp-notify ENOENT` | Executable not on PATH | Use `uvx ... telegram-mcp-notify` or `python -m telegram_mcp_notify.server` |
| `spawn uvx ENOENT` | `uv` not installed/on PATH | Install `uv` and restart the client app |

## License

MIT
