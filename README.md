# telegram-mcp-notify

Telegram notification MCP server with bidirectional reply support for AI coding agents (Cursor, Codex, Claude Code).

## IMPORTANT DISCLAIMER (WIP / SELF-USE)

> [!WARNING]
> This repository is still in active development and currently intended for personal/self use and experimentation.
> APIs and behavior may change at any time without notice.
> Security hardening and production reliability are not guaranteed yet.
> Feel free to try it out, but use it at your own risk.

## Features

- **Outbound notifications**: Send structured Telegram messages for questions, plans, errors, final results, and attention-needed events.
- **Inbound replies**: Receive user responses via text commands, inline keyboards, or polls.
- **High-level input tools**: `ask_user`, `ask_user_confirmation`, `ask_user_choice` for simplified user interaction.
- **Singleton lifecycle**: File-based locking ensures only one server/listener runs at a time.
- **Self-healing listener**: Automatic stale PID/lock cleanup and restart.
- **Cross-platform**: Works on Windows (msvcrt) and POSIX (fcntl).

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
args = ["--from", "git+https://github.com/hyper-tew/telegram-mcp-notify", "telegram-mcp-notify"]

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
  -- uvx --from "git+https://github.com/hyper-tew/telegram-mcp-notify" telegram-mcp-notify
```

---

## Alternative: Pre-install with pip

If you prefer to install the package first (e.g. for pinning a version or offline use):

```bash
# From GitHub
pip install git+https://github.com/hyper-tew/telegram-mcp-notify.git

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

Example with optional vars in Cursor:

```json
{
  "mcpServers": {
    "telegram_notify": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/hyper-tew/telegram-mcp-notify", "telegram-mcp-notify"],
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
curl -fsSL https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/main/.agents/skills/telegram-notify/SKILL.md \
  -o ~/.cursor/skills/telegram-notify/SKILL.md
curl -fsSL https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/main/.agents/skills/telegram-notify/openai.yaml \
  -o ~/.cursor/skills/telegram-notify/openai.yaml

# Codex
mkdir -p ~/.agents/skills/telegram-notify
curl -fsSL https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/main/.agents/skills/telegram-notify/SKILL.md \
  -o ~/.agents/skills/telegram-notify/SKILL.md
curl -fsSL https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/main/.agents/skills/telegram-notify/openai.yaml \
  -o ~/.agents/skills/telegram-notify/openai.yaml
```

On Windows (PowerShell):

```powershell
# Cursor
New-Item -ItemType Directory -Path "$HOME\.cursor\skills\telegram-notify" -Force
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/main/.agents/skills/telegram-notify/SKILL.md" `
  -OutFile "$HOME\.cursor\skills\telegram-notify\SKILL.md"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/main/.agents/skills/telegram-notify/openai.yaml" `
  -OutFile "$HOME\.cursor\skills\telegram-notify\openai.yaml"

# Codex
New-Item -ItemType Directory -Path "$HOME\.agents\skills\telegram-notify" -Force
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/main/.agents/skills/telegram-notify/SKILL.md" `
  -OutFile "$HOME\.agents\skills\telegram-notify\SKILL.md"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/hyper-tew/telegram-mcp-notify/main/.agents/skills/telegram-notify/openai.yaml" `
  -OutFile "$HOME\.agents\skills\telegram-notify\openai.yaml"
```

Restart Cursor or Codex after installing the skill.

### Skill/MCP sanity check

1. Verify MCP server wiring:
   - `codex mcp get telegram_notify`
   - Ensure the command points to the full server entrypoint (`telegram-mcp-notify`, `uvx ... telegram-mcp-notify`, or your wrapper that imports `telegram_mcp_notify.server`).
2. Verify tool coverage in runtime:
   - Full input mode should expose `ask_user` and `check_pending_prompt` (plus listener lifecycle tools).
   - If only `send_telegram_notification` is exposed, treat it as notify-only mode and do not claim reply listening.
3. Restart Codex/Cursor after MCP or skill file changes.
4. Plan Mode clarification routing policy:
   - In Plan Mode, direct clarification questions should be sent through Telegram input tools first.
   - Recommended type-aware routing: binary -> `ask_user_confirmation`; 3+ options -> `ask_user_choice`; free-form only when options are not feasible.
   - Wait for reply using `wait_pending_prompt` (then `check_pending_prompt` if needed).
   - If Telegram input tools are unavailable or fail, explicitly state the reason and fall back to one in-UI question (`request_user_input`).

---

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
| `wait_pending_prompt` | Block until prompt is resolved/expired/cancelled or timeout |
| `list_pending_prompts` | List prompts by session with status filter |

### Lifecycle Tools

| Tool | Description |
|------|-------------|
| `telegram_listener_health` | Listener health diagnostics |
| `start_telegram_listener` | Start the reply listener daemon |
| `repair_telegram_listener` | Repair stale PID/lock and optionally restart |

### Diagnostic Tools

| Tool | Description |
|------|-------------|
| `telegram_notify_capabilities` | Return exposed tool names/groups and supported interaction modes |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| No notifications received | Bot token or chat ID wrong | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` |
| Prompt stays "waiting" | Listener not running | Call `start_telegram_listener` or `repair_telegram_listener` |
| "stale_lock" health reason | Previous listener crashed | Call `repair_telegram_listener(restart=true)` |
| "heartbeat_stale" | Listener froze or network issue | Call `repair_telegram_listener(restart=true)` |
| Prompt expired | User didn't respond in time | Increase `timeout_minutes` or re-ask |
| Inline button not responding | Callback not matched | Ensure listener is running via `telegram_listener_health` |
| `Client error for command spawn telegram-mcp-notify ENOENT` | Executable not installed or not on app PATH | Use `uvx --from git+https://github.com/hyper-tew/telegram-mcp-notify telegram-mcp-notify` in MCP config, or switch to `python -m telegram_mcp_notify.server` |
| `Client error for command spawn uvx ENOENT` | `uv`/`uvx` is not installed or not on app PATH | Install `uv` and restart the app, or use the pip-based `python -m telegram_mcp_notify.server` configuration |

## Data Paths

All data defaults to `~/.telegram-mcp-notify/`:
- `inbox.db` -- SQLite inbox database
- `listener.log` -- Listener log file
- `locks/` -- Singleton lock files

Override with environment variables: `TELEGRAM_INBOX_DB_PATH`, `TELEGRAM_LISTENER_LOG_PATH`, `TELEGRAM_SINGLETON_LOCK_DIR`.

## License

MIT
