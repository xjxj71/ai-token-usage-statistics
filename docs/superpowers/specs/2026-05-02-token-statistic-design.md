# AI Token Statistic - Design Spec

## Context

在 WSL 环境中同时使用多个 AI coding agent（OpenClaw、Hermes、Claude Code），无法统一追踪各 agent 的 token 消耗和费用。需要一个在 Windows 上运行的监控工具，实时采集各 agent 的 token 使用数据，通过 Web Dashboard 展示统计和趋势。

## System Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Windows Native                      │
│                                                      │
│  ┌──────────────┐    SSE     ┌──────────────────┐   │
│  │  Svelte SPA  │◄──────────│   FastAPI Server  │   │
│  │  (Browser)   │           │                  │   │
│  └──────────────┘           │  ┌─────────────┐ │   │
│                             │  │  SQLite DB   │ │   │
│                             │  └─────────────┘ │   │
│                             │                  │   │
│                             │  ┌─────────────┐ │   │
│                             │  │ Collectors   │ │   │
│                             │  │ (per-agent)  │ │   │
│                             │  └──────┬──────-┘ │   │
│                             └─────────┼─────────┘   │
│                                       │              │
│              \\wsl$\Ubuntu\...         │ wsl -e ...   │
└───────────────────────────────────────┼──────────────┘
                                        │
┌───────────────────────────────────────┼──────────────┐
│                       WSL             │              │
│                                       ▼              │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐       │
│  │OpenClaw  │  │ Hermes   │  │ Claude Code  │  ...   │
│  │sessions  │  │state.db  │  │ hook JSON    │       │
│  └──────────┘  └──────────┘  └──────────────┘       │
└──────────────────────────────────────────────────────┘
```

**Runtime**: Python 3.11+ on Windows native, access WSL via `\\wsl$\<distro>\` UNC paths. The WSL distro name is configurable (default: `Ubuntu`).

## Data Collection (Collectors)

Each agent has a dedicated collector plugin. All collectors run on a polling interval (e.g., 5 seconds) and write normalized records to the central SQLite database.

**Incremental reading**: Each collector tracks the last-read position (file offset, DB row ID, or timestamp) in a small state file under `data/collector_state.json`. On each poll, only new records since the last position are processed, avoiding duplicates and minimizing I/O.

### Claude Code

- **Primary**: PostToolUse hook in `settings.json` writes token data to a JSON file in `~/.claude/token-statistic/` (inside WSL). The hook script runs within WSL Python.
- **Fallback**: Parse log files from `~/.claude/logs/`
- **Hook config**: User adds a hook entry in WSL's `~/.claude/settings.json` pointing to a WSL-side script that writes JSON:
  ```json
  {
    "hooks": {
      "PostToolUse": [{
        "command": "python3 ~/.claude/token-statistic/report_token.py '$TOOL_INPUT'"
      }]
    }
  }
  ```
- **Token data source**: Hook receives usage data including input/output/cache tokens and model name
- **Collection**: Windows-side collector polls `\\wsl$\<distro>\home\<user>\.claude\token-statistic\` for new JSON files, processes them, then archives

### Hermes (Nous Research)

- **Primary**: Read `~/.hermes/state.db` SQLite database directly
- **Target table**: `sessions` table with columns: `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `estimated_cost_usd`, `actual_cost_usd`, `cost_status`, `billing_provider`
- **Fallback**: Parse log files from `~/.hermes/logs/agent.log`
- **Access**: Read-only via `\\wsl$\Ubuntu\home\{user}\.hermes\state.db` (copy to temp, then read)

### OpenClaw

- **Primary**: Read `~/.openclaw/agents/{agentId}/sessions/sessions.json`
- **Data fields**: `inputTokens`, `outputTokens`, `totalTokens`, `cacheRead`, `cacheWrite`, `contextTokens`, `estimatedCostUsd`
- **Fallback**: Parse JSONL transcripts from `~/.openclaw/agents/{agentId}/sessions/{sessionId}.jsonl`
- **Config**: `~/.openclaw/openclaw.json` (JSON5 format)

### Collector Interface

```python
class BaseCollector(ABC):
    @abstractmethod
    def collect(self) -> list[TokenRecord]: ...
    
    @abstractmethod  
    def get_last_timestamp(self) -> str | None: ...

@dataclass(frozen=True)
class TokenRecord:
    timestamp: str          # ISO 8601
    agent: str              # 'claude-code' | 'hermes' | 'openclaw'
    model: str              # e.g. 'claude-sonnet-4-6'
    session_id: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    raw_data: str           # Original JSON for debugging
```

New agents are added by implementing `BaseCollector` and registering in the collector registry.

## Data Model

```sql
CREATE TABLE token_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,
    agent             TEXT NOT NULL,
    model             TEXT NOT NULL,
    session_id        TEXT,
    input_tokens      INTEGER DEFAULT 0,
    output_tokens     INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    cost_usd          REAL DEFAULT 0.0,
    raw_data          TEXT
);

CREATE TABLE model_pricing (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    model             TEXT NOT NULL UNIQUE,
    input_price       REAL NOT NULL,       -- per 1M tokens (USD)
    output_price      REAL NOT NULL,
    cache_read_price  REAL DEFAULT 0.0,
    cache_write_price REAL DEFAULT 0.0,
    updated_at        TEXT NOT NULL
);

CREATE INDEX idx_token_usage_ts    ON token_usage(timestamp);
CREATE INDEX idx_token_usage_agent ON token_usage(agent);
CREATE INDEX idx_token_usage_model ON token_usage(model);
CREATE INDEX idx_token_usage_comp  ON token_usage(timestamp, agent, model);
```

## API Design

### REST Endpoints

```
GET /api/summary
    ?range=today|7d|30d|custom
    &from=2026-05-01&to=2026-05-02
    &agent=claude-code,hermes
    &model=claude-sonnet-4-6
    &group_by=agent|model|date
    
    Response: {
      total_tokens: int,          // input + output + cache_read + cache_write
      input_tokens: int,
      output_tokens: int,
      cache_read_tokens: int,
      cache_write_tokens: int,
      cache_tokens: int,          // cache_read + cache_write (convenience)
      cost_usd: float,
      call_count: int,
      breakdown: [{ agent, model, tokens, cost, ... }]
    }

GET /api/usage
    ?page=1&limit=50
    &agent=...&model=...
    &from=...&to=...
    
    Response: {
      items: [TokenRecord],
      total: int,
      page: int
    }

GET /api/agents       -- List tracked agents
GET /api/models       -- List models + pricing
GET /api/pricing      -- Full pricing table

GET /api/stream       -- SSE endpoint for near-real-time updates
    Event: { type: "new_record", data: TokenRecord }
```

### SSE Stream

- Server sends events when new token records are collected
- Client reconnects automatically on disconnect
- Events include the new record data for immediate display

## Frontend (Svelte SPA)

### Tech Stack

- **Svelte** — Compiled, no virtual DOM, small bundle
- **ECharts** — Rich charts with good Chinese locale support
- **TailwindCSS** — Rapid layout styling

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  [Logo] AI Token Statistic    [今日] [7日] [30日] [自定义] │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │总 Token │ │总 Input │ │总 Output│ │总 Cache │       │
│  │ 2.43M   │ │ 1.2M    │ │ 340K    │ │ 890K    │       │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │
│  ┌─────────┐ ┌─────────┐                                │
│  │ 总费用  │ │ 调用次数│                                │
│  │ $12.50  │ │ 156     │                                │
│  └─────────┘ └─────────┘                                │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │         Token Consumption Trend (Line/Bar)        │   │
│  │     Color-coded by agent, toggle token type       │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  ┌────────────────────┐  ┌─────────────────────────┐   │
│  │ Agent Dist (Pie)   │  │ Model Dist (Stacked)     │   │
│  └────────────────────┘  └─────────────────────────┘   │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │         Recent Usage Table (Paginated)            │   │
│  │  Time | Agent | Model | Input | Output | Cost     │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
├─────────────────────────────────────────────────────────┤
│  Filters: [Agent v] [Model v] [Token Type v] [Refresh]  │
└─────────────────────────────────────────────────────────┘
```

### Features

- **Time range tabs**: One-click switch between today / 7d / 30d / custom date picker
- **Multi-select filters**: Agent, model, token type dropdowns
- **Chart interaction**: ECharts hover tooltips, click-to-drill-down
- **Near real-time**: SSE auto-updates cards and charts without page reload
- **Responsive**: Adapt to different window widths

## Project Structure

```
ai-token-statistic/
├── backend/
│   ├── main.py                  # FastAPI entry point
│   ├── config.py                # Settings (WSL path, polling interval, etc.)
│   ├── db/
│   │   ├── database.py          # SQLite connection + migrations
│   │   └── models.py            # Dataclass / query helpers
│   ├── collectors/
│   │   ├── base.py              # BaseCollector ABC
│   │   ├── claude_code.py       # Claude Code collector
│   │   ├── hermes.py            # Hermes collector
│   │   └── openclaw.py          # OpenClaw collector
│   ├── api/
│   │   ├── summary.py           # /api/summary endpoint
│   │   ├── usage.py             # /api/usage endpoint
│   │   ├── models.py            # /api/models endpoint
│   │   └── stream.py            # /api/stream SSE endpoint
│   ├── pricing/
│   │   └── model_pricing.py     # Cost calculation + pricing data
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.svelte
│   │   ├── main.ts
│   │   ├── components/
│   │   │   ├── StatCard.svelte
│   │   │   ├── TrendChart.svelte
│   │   │   ├── AgentPie.svelte
│   │   │   ├── ModelBar.svelte
│   │   │   ├── UsageTable.svelte
│   │   │   ├── FilterBar.svelte
│   │   │   └── TimeRangeTabs.svelte
│   │   ├── api/
│   │   │   └── client.ts        # Fetch wrapper + SSE client
│   │   └── types/
│   │       └── index.ts         # TypeScript interfaces
│   ├── index.html
│   ├── vite.config.ts
│   ├── svelte.config.js
│   ├── tailwind.config.js
│   └── package.json
├── data/
│   └── token_statistic.db       # SQLite database (runtime)
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-05-02-token-statistic-design.md
├── pyproject.toml
└── README.md
```

## Cost Estimation

Each model has a per-1M-token price. The `model_pricing` table stores these rates. When a record is collected:

```
cost_usd = (input_tokens * input_price + output_tokens * output_price 
           + cache_read_tokens * cache_read_price + cache_write_tokens * cache_write_price) / 1_000_000
```

Pre-populated pricing for common models:
- Claude Opus 4.7, Sonnet 4.6, Haiku 4.5
- GPT-4o, GPT-4.1, o3, o4-mini
- Gemini 2.5 Pro/Flash
- DeepSeek V3/R1

## Verification

1. **Unit tests**: Each collector's parsing logic with sample data
2. **Integration test**: End-to-end from collector -> DB -> API -> response
3. **Manual test**: 
   - Start FastAPI server (`uvicorn backend.main:app`)
   - Open browser to `http://localhost:8000`
   - Run an agent in WSL, verify data appears in dashboard within seconds
   - Switch time ranges, apply filters, verify correct aggregation
   - Check SSE stream updates in real-time

## Out of Scope (Future)

- Multi-user support
- Alerting / budget thresholds
- Data export (CSV/JSON)
- Historical comparison (week-over-week)
- Agent process monitoring (CPU/memory)
