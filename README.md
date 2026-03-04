# telegram-mcp-notify

Telegram notification MCP server for AI coding agents (Cursor, Codex, Claude Code).

> Branch note: `feature/notify-only` is a notify-only variant. Telegram reply/input tools are intentionally not exposed.

## IMPORTANT DISCLAIMER (WIP / SELF-USE)

> [!WARNING]
> This repository is still in active development and currently intended for personal/self use and experimentation.
> APIs and behavior may change at any time without notice.
> Security hardening and production reliability are not guaranteed yet.
> Feel free to try it out, but use it at your own risk.

## Features

- **Outbound notifications**: Send structured Telegram messages for `question`, `plan_ready`, `final`, and critical manual-attention alerts.
- **Notify-only MCP surface**: Exposes only `send_telegram_notification` and `telegram_notify_capabilities`.
- **Low-noise workflow**: Designed for checkpoint notifications, not routine progress spam.
- **Cross-platform**: Works on Windows and POSIX.

## Prerequisites

- **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or `pip`
- **Telegram bot token** -- create one via [@BotFather](https://t.me/BotFather)
- **Telegram chat ID** -- send any message to your bot, then open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and look for `"chat":{"id": ...}`

## Credential Safety (Before Going Public)

- Keep `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` only in local config/env files.
- Never commit real credentials to tracked files, issue comments, or PR descriptions.
- Always run `git status` before committing to confirm no local config files are staged.

---

## Quick Start -- Cursor

No pre-installation required. Cursor launches the server on demand via `uvx`.
This path requires `uvx` on PATH (`uvx --version`). If `uvx` is unavailable, use the pip-based setup in the next section.

Create `.cursor/mcp.json` in your project root (or `~/.cursor/mcp.json` for global):

```json
{
  "mcpServers": {
    "telegram_notify": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/hyper-tew/telegram-mcp-notify@feature/notify-only",
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

Replace the `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` values with your own credentials.

If you currently have `"command": "telegram-mcp-notify"` in Cursor config and see `spawn telegram-mcp-notify ENOENT`, switch to the `uvx` config above.

Restart Cursor after saving the file.

## Quick Start -- Codex

No pre-installation required. Codex launches the server on demand via `uvx`.
This path requires `uvx` on PATH (`uvx --version`). If `uvx` is unavailable, use the pip-based setup in the next section.

**Option A -- Edit config.toml**

Add to `~/.codex/config.toml` (global) or `.codex/config.toml` (project-scoped, trusted projects only):

```toml
[mcp_servers.telegram_notify]
command = "uvx"
args = ["--from", "git+https://github.com/hyper-tew/telegram-mcp-notify@feature/notify-only", "telegram-mcp-notify"]

[mcp_servers.telegram_notify.env]
TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."
TELEGRAM_CHAT_ID = "123456789"
```

Replace the token and chat ID values with your own credentials.

**Option B -- CLI one-liner**

```bash
codex mcp add telegram_notify \
  --env TELEGRAM_BOT_TOKEN=123456:ABC-DEF... \
  --env TELEGRAM_CHAT_ID=123456789 \
  -- uvx --from "git+https://github.com/hyper-tew/telegram-mcp-notify@feature/notify-only" telegram-mcp-notify
```

## Tracked Config Templates

This repo includes ready-to-copy templates that pin the MCP source to this branch:

- [docs/config-examples/cursor.mcp.json](docs/config-examples/cursor.mcp.json)
- [docs/config-examples/codex.config.toml](docs/config-examples/codex.config.toml)

---

## Alternative: Pre-install with pip

If you prefer to install the package first (e.g. for pinning a version or offline use):

```bash
# From GitHub
pip install git+https://github.com/hyper-tew/telegram-mcp-notify.git@feature/notify-only

# From a local clone
pip install ./telegram-mcp-notify

# Development (editable + test deps)
pip install -e "./telegram-mcp-notify[dev]"
```

After pre-install, prefer launching through Python module mode (more reliable on Windows PATH setups):

**Cursor** (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "telegram_notify": {
      "command": "python",
      "args": ["-m", "telegram_mcp_notify.server"],
      "env": {
        "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF...",
        "TELEGRAM_CHAT_ID": "123456789"
      }
    }
  }
}
```

**Codex** (`~/.codex/config.toml`):

```toml
[mcp_servers.telegram_notify]
command = "python"
args = ["-m", "telegram_mcp_notify.server"]

[mcp_servers.telegram_notify.env]
TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."
TELEGRAM_CHAT_ID = "123456789"
```

You can still use `command = "telegram-mcp-notify"` only if that executable is on PATH for the app process (verify with `where telegram-mcp-notify` on Windows or `which telegram-mcp-notify` on Linux/macOS).

---

## Optional Environment Variables

Add any of these alongside the required credentials in the same `env` block:

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_PARSE_MODE` | None | Message parse mode (`HTML` or `Markdown`) |
| `TELEGRAM_DISABLE_NOTIFICATION` | `false` | Suppress all notifications |
| `TELEGRAM_TIMEOUT_SECONDS` | `10` | HTTP request timeout |
| `TELEGRAM_INBOX_DB_PATH` | `~/.telegram-mcp-notify/inbox.db` | SQLite inbox path |
| `TELEGRAM_LISTENER_LOG_PATH` | `~/.telegram-mcp-notify/listener.log` | Listener log path |
| `TELEGRAM_SINGLETON_LOCK_DIR` | `~/.telegram-mcp-notify/locks/` | Lock file directory |
| `TELEGRAM_LIFECYCLE_V2` | `true` | Enable lifecycle-v2 robustness controls |
| `TELEGRAM_LISTENER_MODE` | `daemon` | Listener lifecycle mode (`daemon` recommended) |
| `TELEGRAM_LISTENER_AUTORESTART` | `true` | Allow auto-restart when listener is unhealthy |
| `TELEGRAM_LISTENER_MAX_START_FAILURES` | `3` | Max consecutive start failures before hard-stop |
| `TELEGRAM_LISTENER_BACKOFF_SECONDS` | `2,5,15` | Retry backoff schedule (seconds) after failures |
| `TELEGRAM_TOKEN_FINGERPRINT` | None | Non-secret token label for diagnostics |

Example with optional vars in Cursor:

```json
{
  "mcpServers": {
    "telegram_notify": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/hyper-tew/telegram-mcp-notify@feature/notify-only", "telegram-mcp-notify"],
      "env": {
        "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF...",
        "TELEGRAM_CHAT_ID": "123456789",
        "TELEGRAM_PARSE_MODE": "HTML",
        "TELEGRAM_TIMEOUT_SECONDS": "15"
      }
    }
  }
}
```

---

## Installing the Agent Skill

This repo includes an agent skill folder at `.agents/skills/telegram-notify/`:
- `SKILL.md` (human-readable workflow)
- `openai.yaml` (machine-readable metadata + MCP tool dependencies)

The skill works with both Cursor and Codex.

### Automatic (project-level)

If you clone this repo, both Cursor and Codex discover the skill automatically from `.agents/skills/`.

### Global install (all projects)

Copy the skill folder to your global skills directory so it is available in every project.

**Cursor:**

```bash
# Linux / macOS
mkdir -p ~/.cursor/skills/telegram-notify
cp .agents/skills/telegram-notify/SKILL.md ~/.cursor/skills/telegram-notify/SKILL.md
cp .agents/skills/telegram-notify/openai.yaml ~/.cursor/skills/telegram-notify/openai.yaml

# Windows (PowerShell)
New-Item -ItemType Directory -Path "$HOME\.cursor\skills\telegram-notify" -Force
Copy-Item ".agents\skills\telegram-notify\SKILL.md" "$HOME\.cursor\skills\telegram-notify\SKILL.md"
Copy-Item ".agents\skills\telegram-notify\openai.yaml" "$HOME\.cursor\skills\telegram-notify\openai.yaml"
```

**Codex:**

```bash
# Linux / macOS
mkdir -p ~/.agents/skills/telegram-notify
cp .agents/skills/telegram-notify/SKILL.md ~/.agents/skills/telegram-notify/SKILL.md
cp .agents/skills/telegram-notify/openai.yaml ~/.agents/skills/telegram-notify/openai.yaml

# Windows (PowerShell)
New-Item -ItemType Directory -Path "$HOME\.agents\skills\telegram-notify" -Force
Copy-Item ".agents\skills\telegram-notify\SKILL.md" "$HOME\.agents\skills\telegram-notify\SKILL.md"
Copy-Item ".agents\skills\telegram-notify\openai.yaml" "$HOME\.agents\skills\telegram-notify\openai.yaml"
```

### Install from GitHub (without cloning)

```bash
# Cursor
mkdir -p ~/.cursor/skills/telegram-notify
curl -fsSL https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/feature/notify-only/.agents/skills/telegram-notify/SKILL.md \
  -o ~/.cursor/skills/telegram-notify/SKILL.md
curl -fsSL https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/feature/notify-only/.agents/skills/telegram-notify/openai.yaml \
  -o ~/.cursor/skills/telegram-notify/openai.yaml

# Codex
mkdir -p ~/.agents/skills/telegram-notify
curl -fsSL https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/feature/notify-only/.agents/skills/telegram-notify/SKILL.md \
  -o ~/.agents/skills/telegram-notify/SKILL.md
curl -fsSL https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/feature/notify-only/.agents/skills/telegram-notify/openai.yaml \
  -o ~/.agents/skills/telegram-notify/openai.yaml
```

On Windows (PowerShell):

```powershell
# Cursor
New-Item -ItemType Directory -Path "$HOME\.cursor\skills\telegram-notify" -Force
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/feature/notify-only/.agents/skills/telegram-notify/SKILL.md" `
  -OutFile "$HOME\.cursor\skills\telegram-notify\SKILL.md"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/feature/notify-only/.agents/skills/telegram-notify/openai.yaml" `
  -OutFile "$HOME\.cursor\skills\telegram-notify\openai.yaml"

# Codex
New-Item -ItemType Directory -Path "$HOME\.agents\skills\telegram-notify" -Force
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/feature/notify-only/.agents/skills/telegram-notify/SKILL.md" `
  -OutFile "$HOME\.agents\skills\telegram-notify\SKILL.md"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/feature/notify-only/.agents/skills/telegram-notify/openai.yaml" `
  -OutFile "$HOME\.agents\skills\telegram-notify\openai.yaml"
```

Restart Cursor or Codex after installing the skill.

### Skill/MCP sanity check

1. Verify MCP server wiring:
   - `codex mcp get telegram_notify`
   - Ensure the command points to the full server entrypoint (`telegram-mcp-notify`, `uvx ... telegram-mcp-notify`, or your wrapper that imports `telegram_mcp_notify.server`).
2. Verify tool coverage in runtime:
   - Notify-only mode should expose only `send_telegram_notification` and `telegram_notify_capabilities`.
3. Restart Codex/Cursor after MCP or skill file changes.
4. Question routing policy:
   - Ask questions in-chat (UI) and use Telegram only to notify before asking.
   - Reserve `error`/`attention_needed` for cases that require manual user attention.

---

## Available Tools

### Notification Tools

| Tool | Description |
|------|-------------|
| `send_telegram_notification` | Send structured notification (event, message, task_name) |

### Diagnostic Tools

| Tool | Description |
|------|-------------|
| `telegram_notify_capabilities` | Return exposed tool names/groups and supported interaction modes |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| No notifications received | Bot token or chat ID wrong | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` |
| Capability output shows more than 2 tools | Wrong branch/runtime | Use `feature/notify-only` and restart client |
| `Client error for command spawn telegram-mcp-notify ENOENT` | Executable not installed or not on app PATH | Use `uvx --from git+https://github.com/hyper-tew/telegram-mcp-notify@feature/notify-only telegram-mcp-notify` in MCP config, or switch to `python -m telegram_mcp_notify.server` |
| `Client error for command spawn uvx ENOENT` | `uv`/`uvx` is not installed or not on app PATH | Install `uv` and restart the app, or use the pip-based `python -m telegram_mcp_notify.server` configuration |

## Data Paths

All data defaults to `~/.telegram-mcp-notify/`:
- `listener.log` -- Server/log output
- `locks/` -- Singleton lock files

Override with environment variables: `TELEGRAM_INBOX_DB_PATH`, `TELEGRAM_LISTENER_LOG_PATH`, `TELEGRAM_SINGLETON_LOCK_DIR`.

## License

MIT
