# AI Token Usage Statistics

Monitor and visualize token consumption of multiple AI coding agents running in WSL, from a Windows-native web dashboard.

## Features

- **Multi-Agent Support**: Collects token usage from Claude Code, Hermes, and OpenClaw via WSL UNC paths
- **Real-Time Dashboard**: SSE-powered updates, no page reload needed
- **Cost Estimation**: Per-model pricing with automatic cost calculation
- **Rich Visualizations**: Trend charts, agent distribution pie, model breakdown bar (ECharts)
- **Time Range Filters**: Today / 7 days / 30 days / custom range
- **Extensible Collectors**: Add new agents by implementing `BaseCollector`

## Architecture

```
Windows Native
┌────────────────┐    SSE     ┌──────────────────┐
│  Svelte SPA    │◄──────────│  FastAPI Server   │
│  (Browser)     │           │  ├─ SQLite DB     │
└────────────────┘           │  └─ Collectors    │
                             └────────┬──────────┘
                                      │ \\wsl$\Ubuntu\...
                             ┌────────┴──────────┐
                             │       WSL         │
                             │  Claude Code      │
                             │  Hermes state.db  │
                             │  OpenClaw sessions│
                             └───────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, aiosqlite, Pydantic |
| Frontend | Svelte 5, TypeScript, ECharts, TailwindCSS, Vite |
| Database | SQLite |
| Real-Time | Server-Sent Events (SSE) |

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- WSL with at least one AI agent installed

### Backend

```bash
# Create virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate  # Linux/WSL
# or: .venv\Scripts\activate  # Windows

pip install -e ".[dev]"

# Start the server
uvicorn backend.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # Development server
npm run build      # Production build (served by FastAPI)
```

### Configuration

Environment variables (prefix `TOKEN_STAT_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `TOKEN_STAT_WSL_DISTRO` | `Ubuntu` | WSL distribution name |
| `TOKEN_STAT_WSL_USER` | `*` (all users) | WSL username to monitor |
| `TOKEN_STAT_POLL_INTERVAL_SECONDS` | `5` | Collector polling interval |
| `TOKEN_STAT_HOST` | `127.0.0.1` | Server bind address |
| `TOKEN_STAT_PORT` | `8000` | Server port |
| `TOKEN_STAT_DB_PATH` | `data/token_statistic.db` | SQLite database path |

### Agent Setup

Each AI agent needs specific configuration to expose token data. See [Agent Setup Guide](docs/agent-setup-guide.md) for detailed instructions.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/summary` | Aggregated token stats with breakdown |
| GET | `/api/usage` | Paginated usage records |
| GET | `/api/agents` | List tracked agents |
| GET | `/api/models` | List models and pricing |
| GET | `/api/stream` | SSE stream for real-time updates |

### Example

```bash
# Today's summary
curl "http://localhost:8000/api/summary?range=today"

# Filter by agent and model
curl "http://localhost:8000/api/summary?range=7d&agent=claude-code&model=claude-sonnet-4-6"

# Recent usage records
curl "http://localhost:8000/api/usage?page=1&limit=50"
```

## Project Structure

```
ai-token-usage-statistics/
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Settings via pydantic-settings
│   ├── api/                 # REST + SSE endpoints
│   ├── collectors/          # Per-agent data collectors
│   ├── db/                  # SQLite connection + schema
│   └── pricing/             # Model pricing + cost calculation
├── frontend/
│   └── src/
│       ├── App.svelte       # Main app component
│       ├── components/      # StatCard, TrendChart, AgentPie, etc.
│       ├── api/             # Fetch wrapper + SSE client
│       └── types/           # TypeScript interfaces
├── tests/                   # pytest test suite
├── docs/                    # Design spec, setup guides
└── pyproject.toml           # Python project config
```

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=backend --cov-report=term-missing

# Lint
ruff check backend/ tests/
```

## License

Private project. All rights reserved.
