# Agent Tool Configuration Guide

This document describes what you need to configure in each agent tool so the token-statistic collector can read token usage data.

---

## 1. Claude Code

Claude Code requires a **PostToolUse hook** to write token data to a JSON file. The collector then reads these files via the WSL filesystem.

### Step 1: Create the hook script

Place the script at `~/.claude/token-statistic/report_token.py` inside WSL:

```bash
mkdir -p ~/.claude/token-statistic
```

Copy the script from this project:
```
backend/collectors/scripts/report_claude_code.py
```

Save it as:
```
~/.claude/token-statistic/report_token.py
```

Make it executable:
```bash
chmod +x ~/.claude/token-statistic/report_token.py
```

### Step 2: Configure the hook

Edit `~/.claude/settings.json` (in WSL) and add the hook:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "type": "command",
        "command": "python3 ~/.claude/token-statistic/report_token.py \"$TOOL_INPUT\""
      }
    ]
  }
}
```

If you already have hooks configured, append to the existing `PostToolUse` array.

### Step 3: Verify

Run Claude Code and use any tool. Check that JSON files appear:

```bash
ls ~/.claude/token-statistic/usage-*.json
```

Each file should look like:
```json
{
  "timestamp": "2026-05-02T10:30:00.123456+00:00",
  "model": "claude-sonnet-4-6",
  "session_id": "abc123",
  "usage": {
    "input_tokens": 1500,
    "output_tokens": 800,
    "cache_read_input_tokens": 500,
    "cache_creation_input_tokens": 200
  }
}
```

### What the collector does

The Windows-side `ClaudeCodeCollector` polls `\\wsl$\Ubuntu\home\<user>\.claude\token-statistic\` every 5 seconds, reads new JSON files since the last check, calculates cost, writes to the central SQLite DB, then the files are left in place (not deleted, so you can debug).

---

## 2. Hermes (Nous Research)

**No configuration required.** Hermes already stores structured token data in a SQLite database.

### Data location

The collector reads from:
```
~/.hermes/state.db
```

The `sessions` table contains: `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `estimated_cost_usd`, `actual_cost_usd`, `model`, `session_id`, `created_at`.

### How it works

The `HermesCollector` copies `state.db` to a temp file on each poll cycle (to avoid SQLite locking issues), reads new rows by tracking the last `rowid`, then cleans up the temp copy.

### Verify data exists

```bash
# Check if Hermes has been used
ls ~/.hermes/state.db

# Query session count
sqlite3 ~/.hermes/state.db "SELECT COUNT(*) FROM sessions;"
```

---

## 3. OpenClaw

**No configuration required.** OpenClaw persists session data as JSON files.

### Data location

The collector reads from:
```
~/.openclaw/agents/<agentId>/sessions/sessions.json
```

Each session entry contains: `inputTokens`, `outputTokens`, `totalTokens`, `cacheRead`, `cacheWrite`, `contextTokens`, `estimatedCostUsd`, `model`, `id`, `updatedAt`.

### How it works

The `OpenClawCollector` scans all agent directories under `~/.openclaw/agents/`, reads each `sessions.json`, and processes entries with timestamps newer than the last collection.

### Verify data exists

```bash
# Check if OpenClaw has been used
ls ~/.openclaw/agents/

# Check session data
ls ~/.openclaw/agents/*/sessions/sessions.json
```

---

## 4. Token Statistic Tool Configuration

Set environment variables to configure the collector:

| Variable | Default | Description |
|----------|---------|-------------|
| `TOKEN_STAT_WSL_DISTRO` | `Ubuntu` | WSL distribution name |
| `TOKEN_STAT_WSL_USER` | (auto-detect) | Your WSL username. Set this for faster startup |
| `TOKEN_STAT_POLL_INTERVAL_SECONDS` | `5` | Collector polling interval |
| `TOKEN_STAT_HOST` | `127.0.0.1` | Server bind address |
| `TOKEN_STAT_PORT` | `8000` | Server port |

### Example startup

```bash
# Windows (PowerShell or CMD)
set TOKEN_STAT_WSL_USER=your_wsl_username
cd "D:\research project\ai-token-usage-statistics"
.venv\Scripts\activate
uvicorn backend.main:app --reload
```

Then open http://127.0.0.1:8000 in your browser.

---

## Quick Reference

| Agent | Config Needed | Data Source | Access Method |
|-------|--------------|-------------|---------------|
| Claude Code | PostToolUse hook + script | `~/.claude/token-statistic/*.json` | File polling |
| Hermes | None | `~/.hermes/state.db` (SQLite) | DB copy + query |
| OpenClaw | None | `~/.openclaw/agents/*/sessions/sessions.json` | File polling |
