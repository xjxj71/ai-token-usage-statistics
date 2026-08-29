# AI Token Usage Statistics

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Svelte 5](https://img.shields.io/badge/Svelte-5-ff3e00.svg)](https://svelte.dev/)

## Screenshot

![Dashboard](docs/ScreenShot.png)

A web dashboard for monitoring and visualizing token consumption and costs of multiple AI coding agents running on Windows / WSL.

## Features

- **Multi-Agent Support**: Collects token usage from Claude Code, Hermes (WSL + Windows), OpenClaw, OpenClaude, MimoCode, OpenCode, and ZCode
- **Real-time Dashboard**: SSE-based push updates, no page refresh needed
- **Project Analytics**: Token usage and cost per project (repo), derived from session working directories (claude-code / openclaude / zcode), with project filtering
- **Reasoning Tokens**: Reasoning (thinking) tokens tracked separately for zcode / opencode / mimocode
- **Session Drill-down**: Session-level aggregates with click-to-expand per-request details
- **Period Comparison**: Stat cards show deltas vs the previous period (today→yesterday same time, 7d→prior 7d)
- **Usage Report**: One-click daily/weekly report (overview, Top agents/models/projects, plan quota) with Markdown copy
- **Quota Monitoring**: Live remaining quota for Zhipu GLM Coding Plan and Xiaomi MiMo Token Plan (requires browser cookie / session token)
- **Cost Estimation**: Built-in model pricing (YAML config with hot-reload), automatic cost calculation
- **CNY Display**: All costs displayed in Chinese Yuan (CNY) with auto-fetched exchange rate (plus manual refresh), one-click pricing refresh from OpenRouter
- **Data Management**: Retention policy (raw details archived into daily aggregates before deletion — trend/summary history is preserved forever) and SQLite backups (daily auto + manual)
- **Rich Charts**: Agent token comparison, agent consumption pie chart, model/project distribution bar charts, cache hit-ratio analysis (ECharts)
- **Time Range Filtering**: Today / 7 days / 30 days / custom range
- **Pagination & Search**: Usage records and model pricing tables support pagination (10/20/50) and search
- **Extensible Collectors**: Implement `BaseCollector` to integrate new agents
- **Dual Environment**: Windows native deployment (UNC paths) and WSL development/testing (auto-detected)

## Architecture

```
Running on Windows Native or WSL
┌────────────────┐    SSE     ┌──────────────────────┐
│  Svelte SPA    │◄──────────│  FastAPI Server       │
│  (Browser)     │           │  ├─ SQLite Database   │
└────────────────┘           │  └─ Collectors        │
                             └────────┬─────────────-┘
                                      │ UNC / Native Path
                             ┌────────┴──────────────┐
                             │       WSL             │
                             │  Claude Code (claude) │
                             │  Hermes (root)        │
                             │  OpenClaw (root)      │
                             └──────────────────────-┘

                             ┌────────────────────────┐
                             │     Windows Local       │
                             │  Hermes-Win (user)      │
                             │  OpenClaude (user)      │
                             │  MimoCode (user)        │
                             │  OpenCode (user)        │
                             │  ZCode (user)           │
                             └────────────────────────┘
```

The backend is designed for Windows native deployment, accessing agent data files in WSL via UNC paths (`\\wsl$\project-claude\...`). It also runs inside WSL for development/testing -- automatically detecting the `is_wsl` environment variable and using Linux native paths.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+, FastAPI, aiosqlite, Pydantic, PyYAML |
| Frontend | Svelte 5, TypeScript, ECharts, TailwindCSS, Vite |
| Database | SQLite |
| Real-time | Server-Sent Events (SSE) |

## Quick Start

### Requirements

- Python 3.11+
- Node.js 18+
- At least one AI agent installed in WSL

### Backend

```bash
# Create virtual environment and install dependencies
python -m venv .venv

# Windows native deployment
.venv\Scripts\activate
# WSL development/testing
source .venv/bin/activate

pip install -e ".[dev]"

# Start server
uvicorn backend.main:app --reload
```

> When running inside WSL, the environment is automatically detected and Linux native paths are used to access data files.

### Frontend

```bash
cd frontend
npm install
npm run dev        # Development server
npm run build      # Production build (served by FastAPI)
```

### Configuration

Configure via environment variables or `config.py` (prefix `TOKEN_STAT_`):

| Variable / Config | Default | Description |
|-------------------|---------|-------------|
| `wsl_distro` / `TOKEN_STAT_WSL_DISTRO` | `project-claude` | WSL distribution name |
| `wsl_user_accessible` | `claude` | WSL user accessible via UNC (data can be read via UNC) |
| `wsl_user_root` | `root` | Root user (for copying data under /root/ via `wsl.exe -u root -- cp`) |
| `poll_interval_seconds` / `TOKEN_STAT_POLL_INTERVAL_SECONDS` | `5` | Collector polling interval (seconds) |
| `db_path` / `TOKEN_STAT_DB_PATH` | `data/token_statistic.db` | Local SQLite database path |
| `TOKEN_STAT_HOST` | `127.0.0.1` | Server bind address |
| `TOKEN_STAT_PORT` | `8001` | Server port |
| `TOKEN_STAT_API_KEY` | empty | API auth key; when empty only local access is allowed. When set, all `/api/` requests must send an `X-API-Key` header |
| `TOKEN_STAT_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | CORS allowed origins (comma-separated; set to your real domain in production) |
| `TOKEN_STAT_USD_TO_CNY_RATE` | `7.25` | Fallback exchange rate (used only when the live rate fetch fails and no previous value exists) |
| `TOKEN_STAT_RETENTION_DAYS` | `0` | Days to keep raw usage details (`0` = forever). Older details are aggregated into `usage_daily` then deleted; editable in the Data Management panel |
| `TOKEN_STAT_BACKUP_KEEP` | `10` | Number of backup files to keep |
| `TOKEN_STAT_AUTO_BACKUP` | `true` | Daily automatic backup into `data/backups/` |
| `TOKEN_STAT_ZHIPU_SESSION_TOKEN` | — | Zhipu Coding Plan session token |
| `TOKEN_STAT_XIAOMI_COOKIE` | — | Xiaomi MiMo Token Plan full cookie |

> **Quota credentials**: Zhipu/Xiaomi credentials can also be stored in `config/quota_providers.yaml` (copy from [`config/quota_providers.example.yaml`](config/quota_providers.example.yaml)). That file holds sensitive credentials and is gitignored — **never commit it**.

### Data Source Paths

| Agent | Data File | WSL Path | Windows Path |
|-------|-----------|----------|--------------|
| Hermes (WSL) | state.db (SQLite) | `/root/.hermes/state.db` → copied to `/tmp/hermes_state.db` | `\\wsl$\project-claude\tmp\hermes_state.db` |
| Hermes (Windows) | state.db (SQLite) | — | `%LOCALAPPDATA%\hermes\state.db` (Windows local, direct read) |
| Claude Code | session JSONL | `/home/claude/.claude/projects/**/*.jsonl` | `\\wsl$\project-claude\home\claude\.claude\projects\` (recursive scan) |
| OpenClaw | sessions.json | `/root/.openclaw/agents/main/sessions/sessions.json` → copied to `/tmp/openclaw_sessions.json` | `\\wsl$\project-claude\tmp\openclaw_sessions.json` |
| OpenClaude | session JSONL | — | `%USERPROFILE%\.openclaude\projects\**\*.jsonl` (Windows local, direct read) |
| MimoCode | mimocode.db (SQLite) | — | `~/.local/share/mimocode/mimocode.db` (Windows local, direct read) |
| OpenCode | opencode.db (SQLite) | — | `~/.local/share/opencode/opencode.db` (Windows local, direct read) |
| ZCode | db.sqlite (SQLite) | — | `~/.zcode/cli/db/db.sqlite` (Windows local, snapshot read) |

> **Permissions**: Hermes (WSL) and OpenClaw data is under `/root/` (mode 700), inaccessible to the default WSL user `claude` via UNC. The collector copies files to `/tmp/` (chmod 644) before reading. On Windows, `wsl.exe -u root -- cp` is used; inside WSL, `shutil.copy2` is used directly. Claude Code data is under the `claude` user directory with no permission issues. Hermes (Windows) data is under `%LOCALAPPDATA%`, readable by the current user.

### Agent Configuration

- **Hermes (WSL)** and **OpenClaw**: No configuration needed, collectors read data files automatically.
- **Hermes (Windows)**: No configuration needed. Collector reads `%LOCALAPPDATA%\hermes\state.db` directly. Runs independently from the WSL collector with agent name `hermes-win`.
- **Claude Code**: No configuration needed. Collector scans all session JSONL files under `~/.claude/projects/`, extracting token data from `message.usage`. Zero intrusion, no action required in Claude Code.
- **OpenClaude**: No configuration needed. Collector scans all session JSONL files under Windows local `%USERPROFILE%\.openclaude\projects\`, same data format as Claude Code. No WSL path conversion or permission handling needed.
- **MimoCode**: No configuration needed. Collector reads `~/.local/share/mimocode/mimocode.db` SQLite database, extracting token usage from assistant messages in the `message` table.
- **OpenCode**: No configuration needed. Collector reads `~/.local/share/opencode/opencode.db` SQLite database, same data format as MimoCode (MiMoCode is a fork of OpenCode).
- **ZCode**: No configuration needed. Collector reads the `model_usage` table (one row per model request with full token accounting) from `~/.zcode/cli/db/db.sqlite`. The db is WAL-mode and actively written by ZCode, so a main+WAL snapshot is copied before querying; in-flight requests are picked up automatically once completed.

See [Agent Setup Guide](docs/agent-setup-guide.md) for details.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/summary` | Summary statistics with agent/model/project breakdowns; `compare=true` adds previous-period totals |
| GET | `/api/usage` | Paginated usage records (supports `session_id` and `project` filters) |
| GET | `/api/sessions` | Session-level aggregates (grouped by agent × session, paginated) |
| GET | `/api/agents` | List of tracked agents |
| GET | `/api/projects` | List of known project names (for filtering) |
| GET | `/api/models` | Model list with pricing |
| GET | `/api/config` | Frontend config (effective exchange rate and its source) |
| POST | `/api/config/exchange-rate/refresh` | Force refresh the live exchange rate (local or API key only) |
| GET | `/api/report` | Usage report (totals + comparison + top lists + quota + Markdown text) |
| GET | `/api/stream` | SSE real-time push stream |
| GET | `/api/pricing` | All model pricing |
| PUT | `/api/pricing/{model}` | Update specific model pricing |
| POST | `/api/pricing/refresh` | One-click refresh all model pricing from OpenRouter |
| GET | `/api/quota` | Quota snapshots for all enabled providers (cached) |
| POST | `/api/quota/refresh` | Force refresh quota |
| GET | `/api/quota/providers` | List configured quota providers and enabled state |
| PUT | `/api/quota/config` | Update provider config (session token, plan type, enabled) |
| GET | `/api/config/data` | Data management settings (retention, backups) |
| PUT | `/api/config/data` | Update data management settings (local or API key only) |
| POST | `/api/maintenance/cleanup` | Run the retention pass now (local or API key only) |
| POST | `/api/backup` | Create a database backup now (local or API key only) |
| GET | `/api/backups` | List backup files |
| GET | `/api/backups/{name}` | Download a backup file |
| DELETE | `/api/backups/{name}` | Delete a backup file (local or API key only) |

### Request Examples

```bash
# Today's summary (starting from midnight Beijing time)
curl "http://localhost:8001/api/summary?range=today"

# Filter by agent and model
curl "http://localhost:8001/api/summary?range=7d&agent=claude-code&model=claude-sonnet-4-6"

# Recent usage records (supports range parameter)
curl "http://localhost:8001/api/usage?range=today&page=1&limit=50"

# Without range, filter by from/to
curl "http://localhost:8001/api/usage?from=2026-05-01&to=2026-05-07"
```

> **Timezone**: `range=today`, `7d`, `30d` all calculate start/end times based on local timezone (Asia/Shanghai). Timestamps in the database are stored in UTC format. The frontend also uses local dates to generate from/to parameters, ensuring cross-timezone consistency.

## Project Structure

```
ai-token-usage-statistics/
├── backend/
│   ├── main.py              # FastAPI application entry
│   ├── config.py            # pydantic-settings configuration
│   ├── exchange_rate.py     # USD→CNY rate (live fetch + cache + fallback)
│   ├── maintenance.py       # Data retention (daily archiving) and backups
│   ├── api/                 # REST + SSE endpoints (summary/usage/sessions/report/maintenance, etc.)
│   ├── collectors/          # Agent data collectors
│   ├── db/                  # SQLite connection, schema and migrations
│   ├── pricing/             # Model pricing and cost calculation
│   └── quota/               # Plan quota monitoring (Zhipu, Xiaomi)
├── frontend/
│   └── src/
│       ├── App.svelte       # Main application component
│       ├── components/      # StatCard, ProjectBar, SessionTable, ReportCard, DataManagement, etc.
│       ├── api/             # API client + SSE client + query params
│       └── types/           # TypeScript type definitions
├── tests/                   # pytest test cases
├── config/                  # Model pricing YAML + quota provider config
├── scripts/                 # Utility scripts (cost recalculation, etc.)
├── docs/                    # Design docs, setup guides
└── pyproject.toml           # Python project config
```

### Data Retention & Backups

- **Retention**: when `retention_days > 0`, raw usage records older than the window are first aggregated into `usage_daily` (per day × agent × model × project) and then deleted. Trend charts, summaries, and cache-ratio analysis automatically UNION the archived data, so **full history is preserved** — only raw "usage records / session details" become invisible past the window. Editing model prices still recalculates historical costs from the archived token counts.
- **Backups**: daily automatic (optional) + manual, stored in `data/backups/`, keeping the newest N files. **To restore**: stop the backend, replace `data/token_statistic.db` with a backup file, and restart.
- **Upgrading an existing database**: the first start after upgrading runs a migration automatically — historical records get `project` (last segment of the session working directory) and `reasoning_tokens` backfilled from `raw_data`. No manual steps needed.

## Testing

```bash
# Run all tests
pytest

# With coverage report
pytest --cov=backend --cov-report=term-missing

# Code linting
ruff check backend/ tests/
```

## License

[MIT License](LICENSE)
