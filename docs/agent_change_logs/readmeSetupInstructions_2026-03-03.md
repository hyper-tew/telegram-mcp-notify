# readmeSetupInstructions -- 2026-03-03

## Index

- 2026-03-03: Initial rewrite -- credentials in env blocks, correct GitHub URL
- 2026-03-03 Update 2 -- uvx zero-install, skills consolidation, install-from-GitHub instructions
- 2026-03-03 Update 3 -- Plan Mode Telegram-first clarification routing in skill/docs

---

## Update 3 -- 2026-03-03

- **Date Applied:** 2026-03-03
- **Motivation:** Ensure repository-local skill/docs match the intended Codex Plan Mode behavior: Telegram-first user questions with explicit in-UI fallback.
- **Main Modified Files:**
  - `.agents/skills/telegram-notify/SKILL.md`
  - `README.md`
  - `docs/agent_change_logs/readmeSetupInstructions_2026-03-03.md`
- **Change Summary:**
  1. Added a mandatory "Plan Mode Question Routing" section to `.agents/skills/telegram-notify/SKILL.md`.
  2. Documented deterministic routing in the skill: binary -> `ask_user_confirmation`, 3+ options -> `ask_user_choice`, and text-only for true free-form needs.
  3. Added wait/fallback behavior to the skill: `wait_pending_prompt` first, `check_pending_prompt` follow-up, then explicit `request_user_input` fallback when Telegram input mode is unavailable/fails.
  4. Added matching policy notes in README under "Skill/MCP sanity check".
- **Before/After (Key Snippet):**

```diff
+## Plan Mode Question Routing (Mandatory)
+When a Plan Mode question requires user input, Telegram is the primary channel and UI questions are fallback-only.
+...
+- If unavailable/failure/timeout:
+  - Emit one explicit warning in chat
+  - Ask exactly once via request_user_input
```

- **Notes/Follow-ups:** Restart Codex/Cursor after skill updates so the runtime reloads the revised skill text.

---

## Update 2 -- 2026-03-03

- **Date Applied:** 2026-03-03
- **Motivation:** Align the repo with standard MCP server distribution patterns (uvx zero-install from GitHub) and the Agent Skills standard (`.agents/skills/`). Make it easy for users to install both the MCP server and the agent skill without cloning the repo.
- **Main Modified Files:**
  - `README.md`
  - `.agents/skills/telegram-notify/SKILL.md` (new -- canonical skill location)
  - `docs/.cursor/SKILL.md` (deleted)
  - `docs/.codex/SKILL.md` (deleted)
- **Change Summary:**
  1. README now uses `uvx --from git+https://github.com/hyper-tew/telegram-mcp-notify telegram-mcp-notify` as the primary install method for both Cursor and Codex, removing the need for a separate `pip install` step.
  2. Added "Alternative: Pre-install with pip" section for users who prefer traditional installation.
  3. Consolidated duplicate skill files from `docs/.cursor/` and `docs/.codex/` into a single `.agents/skills/telegram-notify/SKILL.md` (standard location recognised by both Cursor and Codex).
  4. Added "Installing the Agent Skill" section with instructions for project-level auto-discovery, global install (copy commands for Linux/macOS/Windows), and install-from-GitHub via curl/Invoke-WebRequest.
- **Before/After (Key Snippet):**

```diff
-"command": "telegram-mcp-notify",
-"args": [],
+"command": "uvx",
+"args": ["--from", "git+https://github.com/hyper-tew/telegram-mcp-notify", "telegram-mcp-notify"],
```

- **Notes/Follow-ups:** If the package is published to PyPI in the future, the `uvx` command can be simplified to just `uvx telegram-mcp-notify`.

---

## Change Details

- **Date Applied:** 2026-03-03
- **Motivation:** README lacked step-by-step setup instructions for Cursor and Codex, did not show how to embed Telegram credentials in the MCP config files, and used a placeholder GitHub URL.
- **Main Modified Files:**
  - `README.md`
- **Change Summary:** Rewrote README.md to add Prerequisites, reorganized Installation with the correct GitHub URL (`hyper-tew/telegram-mcp-notify`), and added dedicated "Setup -- Cursor" and "Setup -- Codex" sections showing how to place `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` directly in `.cursor/mcp.json` (via `env` object) and `~/.codex/config.toml` (via `[mcp_servers.telegram_notify.env]` table). Added an "Optional Configuration" section for additional env vars. Kept all existing tool reference, environment variable, troubleshooting, and data path sections intact.
- **Before/After (Key Snippet):**

```diff
-## MCP Configuration
-
-### Cursor (`.mcp.json` or `.cursor/mcp.json`)
-
-```json
-{
-  "mcpServers": {
-    "telegram_notify": {
-      "command": "telegram-mcp-notify",
-      "args": []
-    }
-  }
-}
-```
-
-### Codex (`~/.codex/config.toml`)
-
-```toml
-[mcp_servers.telegram_notify]
-command = "telegram-mcp-notify"
-args = []
-```

+## Setup -- Cursor
+
+```json
+{
+  "mcpServers": {
+    "telegram_notify": {
+      "command": "telegram-mcp-notify",
+      "args": [],
+      "env": {
+        "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF...",
+        "TELEGRAM_CHAT_ID": "123456789"
+      }
+    }
+  }
+}
+```
+
+## Setup -- Codex
+
+```toml
+[mcp_servers.telegram_notify]
+command = "telegram-mcp-notify"
+args = []
+
+[mcp_servers.telegram_notify.env]
+TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."
+TELEGRAM_CHAT_ID = "123456789"
+```
```

- **Notes/Follow-ups:** None.
