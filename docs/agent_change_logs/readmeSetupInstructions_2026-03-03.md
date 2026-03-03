# readmeSetupInstructions -- 2026-03-03

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
