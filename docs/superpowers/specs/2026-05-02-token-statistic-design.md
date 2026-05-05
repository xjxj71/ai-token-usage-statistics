# AI Token 用量统计 - 设计规格

## 背景

在 WSL 环境中同时使用多个 AI 编程 Agent（OpenClaw、Hermes、Claude Code），无法统一追踪各 Agent 的 Token 消耗和费用。需要一个在 Windows 上运行的监控工具，实时采集各 Agent 的 Token 使用数据，通过 Web 仪表盘展示统计和趋势。

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│          Windows 原生 或 WSL 内运行                    │
│                                                      │
│  ┌──────────────┐    SSE     ┌──────────────────┐   │
│  │  Svelte SPA  │◄──────────│   FastAPI 服务器   │   │
│  │  (浏览器)    │           │                  │   │
│  └──────────────┘           │  ┌─────────────┐ │   │
│                             │  │  SQLite 数据库│ │   │
│                             │  └─────────────┘ │   │
│                             │                  │   │
│                             │  ┌─────────────┐ │   │
│                             │  │   采集器     │ │   │
│                             │  │  (按 Agent)  │ │   │
│                             │  └──────┬──────-┘ │   │
│                             └─────────┼─────────┘   │
│                                       │              │
│              \\wsl$\project-claude\... │ wsl_copy_to_tmp()
└───────────────────────────────────────┼──────────────┘
                                        │
┌───────────────────────────────────────┼──────────────┐
│                       WSL             │              │
│                                       ▼              │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐       │
│  │OpenClaw  │  │ Hermes   │  │ Claude Code  │  ...   │
│  │sessions  │  │state.db  │  │ costs.jsonl  │       │
│  │(/root/)  │  │(/root/)  │  │(claude)      │       │
│  └──────────┘  └──────────┘  └──────────────┘       │
│         ↓ copy       ↓ copy        ↓ direct         │
│  ┌──────────────────────────────────────────────┐   │
│  │  /tmp/hermes_state.db / /tmp/openclaw_*.json  │   │
│  └──────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
```

**运行环境**：设计为 Windows 本机运行 Python 3.11+，通过 `\\wsl$\<distro>\` UNC 路径访问 WSL。同时也支持在 WSL 内直接运行（自动检测 `is_wsl`，使用 Linux 原生路径）。WSL 发行版名称可配置（默认：`project-claude`）。

## 数据采集（采集器）

每个 Agent 有一个专属的采集器插件。所有采集器按轮询间隔（如 5 秒）运行，将标准化记录写入中央 SQLite 数据库。

**增量读取**：每个采集器在 `data/collector_state.json` 中追踪上次读取位置（文件偏移、数据库行 ID 或时间戳）。每次轮询仅处理上次位置之后的新记录，避免重复并最小化 I/O。

### Claude Code

- **主要方式**：直接读取 Claude Code 自动生成的 `~/.claude/metrics/costs.jsonl` 文件
- **数据格式**：JSONL 文件，每行一个 JSON 对象：`{timestamp, session_id, model, input_tokens, output_tokens, estimated_cost_usd}`
- **采集方式**：
  - Windows 部署：通过 UNC 路径 `\\wsl$\project-claude\home\claude\.claude\metrics\costs.jsonl` 读取
  - WSL 内测试：通过原生路径 `/home/claude/.claude/metrics/costs.jsonl` 读取
  - 增量读取：追踪文件偏移量，每次仅处理新增行
- **注意事项**：当前 `costs.jsonl` 全是零数据（model=unknown, tokens=0），属于占位采集

### Hermes (Nous Research)

- **主要方式**：读取 `/root/.hermes/state.db` SQLite 数据库
- **目标表**：`sessions` 表，包含列：`started_at`（REAL Unix 时间戳）、`model`、`input_tokens`、`output_tokens`、`cache_read_tokens`、`cache_write_tokens`、`estimated_cost_usd`、`actual_cost_usd`、`cost_status`、`billing_provider`
- **访问方式**：数据文件位于 `/root/` 下（权限 700），需通过 `wsl_copy_to_tmp()` 复制到 `/tmp/hermes_state.db`（chmod 644）后读取
  - Windows 部署：`wsl.exe -u root -- cp /root/.hermes/state.db /tmp/hermes_state.db && chmod 644 /tmp/hermes_state.db`
  - WSL 内测试：`shutil.copy2()` 直接复制（运行用户即 root）

### OpenClaw

- **主要方式**：读取 `/root/.openclaw/agents/main/sessions/sessions.json`
- **数据格式**：JSON 对象（dict，非 list），key 为 agent session 名（如 `"agent:main:main"`），value 包含 `sessionId`、`updatedAt`（毫秒时间戳）、`totalTokens`、`inputTokens`、`outputTokens`、`cacheRead`、`cacheWrite`、`estimatedCostUsd`、`model` 等
- **访问方式**：数据文件位于 `/root/` 下（权限 700），需通过 `wsl_copy_to_tmp()` 复制到 `/tmp/openclaw_sessions.json`（chmod 644）后读取
  - Windows 部署：`wsl.exe -u root -- cp /root/.openclaw/agents/main/sessions/sessions.json /tmp/openclaw_sessions.json && chmod 644 /tmp/openclaw_sessions.json`
  - WSL 内测试：`shutil.copy2()` 直接复制（运行用户即 root）

### 采集器接口

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
    model: str              # 如 'claude-sonnet-4-6'
    session_id: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    raw_data: str           # 原始 JSON，用于调试
```

新增 Agent 只需实现 `BaseCollector` 并在采集器注册表中注册即可。

## 数据模型

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
    input_price       REAL NOT NULL,       -- 每百万 Token（美元）
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

## API 设计

### REST 端点

```
GET /api/summary
    ?range=today|7d|30d|custom
    &from=2026-05-01&to=2026-05-02
    &agent=claude-code,hermes
    &model=claude-sonnet-4-6
    &group_by=agent|model|date

    响应: {
      total_tokens: int,          // input + output + cache_read + cache_write
      input_tokens: int,
      output_tokens: int,
      cache_read_tokens: int,
      cache_write_tokens: int,
      cache_tokens: int,          // cache_read + cache_write（便捷字段）
      cost_usd: float,
      call_count: int,
      breakdown: [{ agent, model, tokens, cost, ... }]
    }

GET /api/usage
    ?page=1&limit=50
    &agent=...&model=...
    &from=...&to=...

    响应: {
      items: [TokenRecord],
      total: int,
      page: int
    }

GET /api/agents       -- 已追踪的 Agent 列表
GET /api/models       -- 模型列表 + 定价
GET /api/pricing      -- 完整定价表

GET /api/stream       -- SSE 实时推送端点
    事件: { type: "new_record", data: TokenRecord }
```

### SSE 流

- 服务器在采集到新 Token 记录时推送事件
- 客户端断连后自动重连
- 事件包含新记录数据，可直接显示

## 前端（Svelte SPA）

### 技术栈

- **Svelte** — 编译时框架，无虚拟 DOM，包体积小
- **ECharts** — 丰富的图表库，中文支持良好
- **TailwindCSS** — 快速布局样式

### 布局

```
┌─────────────────────────────────────────────────────────┐
│  [Logo] AI Token 统计    [今日] [7日] [30日] [自定义]      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │总 Token │ │总输入   │ │总输出   │ │总缓存   │       │
│  │ 2.43M   │ │ 1.2M    │ │ 340K    │ │ 890K    │       │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │
│  ┌─────────┐ ┌─────────┐                                │
│  │ 总费用  │ │ 调用次数│                                │
│  │ $12.50  │ │ 156     │                                │
│  └─────────┘ └─────────┘                                │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │         Token 消耗趋势（折线/柱状图）              │   │
│  │     按 Agent 着色，可切换 Token 类型               │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  ┌────────────────────┐  ┌─────────────────────────┐   │
│  │ Agent 分布（饼图） │  │ 模型分布（堆叠柱状图）   │   │
│  └────────────────────┘  └─────────────────────────┘   │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │         最近使用记录（分页表格）                    │   │
│  │  时间 | Agent | 模型 | 输入 | 输出 | 费用          │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
├─────────────────────────────────────────────────────────┤
│  筛选: [Agent ▾] [模型 ▾] [Token 类型 ▾] [刷新]         │
└─────────────────────────────────────────────────────────┘
```

### 功能特性

- **时间范围切换**：一键切换今日 / 7天 / 30天 / 自定义日期
- **多选筛选**：Agent、模型、Token 类型下拉菜单
- **图表交互**：ECharts 悬浮提示，点击下钻
- **近实时更新**：SSE 自动更新卡片和图表，无需刷新页面
- **响应式布局**：适配不同窗口宽度

## 项目结构

```
ai-token-statistic/
├── backend/
│   ├── main.py                  # FastAPI 应用入口
│   ├── config.py                # 配置（WSL 路径、轮询间隔等）
│   ├── db/
│   │   ├── database.py          # SQLite 连接 + 迁移
│   │   └── models.py            # 数据类 / 查询辅助
│   ├── collectors/
│   │   ├── base.py              # BaseCollector 抽象基类
│   │   ├── claude_code.py       # Claude Code 采集器
│   │   ├── hermes.py            # Hermes 采集器
│   │   └── openclaw.py          # OpenClaw 采集器
│   ├── api/
│   │   ├── summary.py           # /api/summary 端点
│   │   ├── usage.py             # /api/usage 端点
│   │   ├── models.py            # /api/models 端点
│   │   └── stream.py            # /api/stream SSE 端点
│   ├── pricing/
│   │   └── model_pricing.py     # 费用计算 + 定价数据
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
│   │   │   └── client.ts        # 请求封装 + SSE 客户端
│   │   └── types/
│   │       └── index.ts         # TypeScript 接口定义
│   ├── index.html
│   ├── vite.config.ts
│   ├── svelte.config.js
│   ├── tailwind.config.js
│   └── package.json
├── data/
│   └── token_statistic.db       # SQLite 数据库（运行时）
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-05-02-token-statistic-design.md
├── pyproject.toml
└── README.md
```

## 费用估算

每个模型都有每百万 Token 的单价。`model_pricing` 表存储这些费率。当采集到一条记录时：

```
cost_usd = (input_tokens * input_price + output_tokens * output_price
           + cache_read_tokens * cache_read_price + cache_write_tokens * cache_write_price) / 1_000_000
```

预置常见模型定价：
- Claude Opus 4.7, Sonnet 4.6, Haiku 4.5
- GPT-4o, GPT-4.1, o3, o4-mini
- Gemini 2.5 Pro/Flash
- DeepSeek V3/R1

## 验证

1. **单元测试**：每个采集器的解析逻辑，使用样本数据
2. **集成测试**：端到端流程：采集器 → 数据库 → API → 响应
3. **手动测试**：
   - 启动 FastAPI 服务器（`uvicorn backend.main:app`）
   - 浏览器打开 `http://localhost:8000`
   - 在 WSL 中运行 Agent，验证数据在几秒内出现在仪表盘
   - 切换时间范围，应用筛选，验证聚合结果正确
   - 检查 SSE 流实时更新

### 已验证的采集结果

| Agent | 记录数 | 说明 |
|-------|--------|------|
| Hermes | 71 条 | 模型 glm-5.1，input_tokens 最高 28,654 |
| Claude Code | 102 条 | 全是零数据（costs.jsonl 本身无有效数据，model=unknown, tokens=0） |
| OpenClaw | 70 条 | 模型包括 mimo-v2-pro, mimo-v2.5-pro, deepseek-v4 等 |

## 暂不实现（未来规划）

- 多用户支持
- 告警 / 预算阈值
- 数据导出（CSV/JSON）
- 历史对比（周环比）
- Agent 进程监控（CPU/内存）
