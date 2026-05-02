# AI Token Usage Statistics

在 Windows 上运行的 Web 仪表盘，用于监控和可视化 WSL 中多个 AI 编程 Agent 的 Token 消耗与费用。

## 功能特性

- **多 Agent 支持**：通过 WSL UNC 路径采集 Claude Code、Hermes、OpenClaw 的 Token 用量
- **实时仪表盘**：基于 SSE 推送更新，无需刷新页面
- **费用估算**：内置各模型定价，自动计算使用成本
- **丰富图表**：趋势折线图、Agent 分布饼图、模型占比柱状图（ECharts）
- **时间范围筛选**：今日 / 7 天 / 30 天 / 自定义区间
- **可扩展采集器**：实现 `BaseCollector` 即可接入新 Agent

## 系统架构

```
Windows 本地
┌────────────────┐    SSE     ┌──────────────────┐
│  Svelte SPA    │◄──────────│  FastAPI Server   │
│  (浏览器)      │           │  ├─ SQLite 数据库  │
└────────────────┘           │  └─ 采集器        │
                             └────────┬──────────┘
                                      │ \\wsl$\Ubuntu\...
                             ┌────────┴──────────┐
                             │       WSL         │
                             │  Claude Code      │
                             │  Hermes state.db  │
                             │  OpenClaw sessions│
                             └───────────────────┘
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11+, FastAPI, aiosqlite, Pydantic |
| 前端 | Svelte 5, TypeScript, ECharts, TailwindCSS, Vite |
| 数据库 | SQLite |
| 实时通信 | Server-Sent Events (SSE) |

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- WSL 中至少安装了一个 AI Agent

### 后端

```bash
# 创建虚拟环境并安装依赖
python -m venv .venv
source .venv/bin/activate  # Linux/WSL
# 或: .venv\Scripts\activate  # Windows

pip install -e ".[dev]"

# 启动服务
uvicorn backend.main:app --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev        # 开发服务器
npm run build      # 生产构建（由 FastAPI 托管）
```

### 配置项

通过环境变量配置（前缀 `TOKEN_STAT_`）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TOKEN_STAT_WSL_DISTRO` | `Ubuntu` | WSL 发行版名称 |
| `TOKEN_STAT_WSL_USER` | `*`（所有用户） | 监控的 WSL 用户名 |
| `TOKEN_STAT_POLL_INTERVAL_SECONDS` | `5` | 采集器轮询间隔（秒） |
| `TOKEN_STAT_HOST` | `127.0.0.1` | 服务绑定地址 |
| `TOKEN_STAT_PORT` | `8000` | 服务端口 |
| `TOKEN_STAT_DB_PATH` | `data/token_statistic.db` | SQLite 数据库路径 |

### Agent 配置

各 AI Agent 需要特定配置才能暴露 Token 数据，详见 [Agent 配置指南](docs/agent-setup-guide.md)。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/summary` | 汇总统计，含按 Agent/模型/日期的明细 |
| GET | `/api/usage` | 分页查询使用记录 |
| GET | `/api/agents` | 获取已追踪的 Agent 列表 |
| GET | `/api/models` | 获取模型列表及定价 |
| GET | `/api/stream` | SSE 实时推送流 |

### 请求示例

```bash
# 今日汇总
curl "http://localhost:8000/api/summary?range=today"

# 按 Agent 和模型筛选
curl "http://localhost:8000/api/summary?range=7d&agent=claude-code&model=claude-sonnet-4-6"

# 最近使用记录
curl "http://localhost:8000/api/usage?page=1&limit=50"
```

## 项目结构

```
ai-token-usage-statistics/
├── backend/
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # pydantic-settings 配置
│   ├── api/                 # REST + SSE 接口
│   ├── collectors/          # 各 Agent 数据采集器
│   ├── db/                  # SQLite 连接与表结构
│   └── pricing/             # 模型定价与费用计算
├── frontend/
│   └── src/
│       ├── App.svelte       # 主应用组件
│       ├── components/      # StatCard, TrendChart, AgentPie 等
│       ├── api/             # 请求封装 + SSE 客户端
│       └── types/           # TypeScript 类型定义
├── tests/                   # pytest 测试用例
├── docs/                    # 设计文档、配置指南
└── pyproject.toml           # Python 项目配置
```

## 测试

```bash
# 运行全部测试
pytest

# 带覆盖率报告
pytest --cov=backend --cov-report=term-missing

# 代码检查
ruff check backend/ tests/
```

## 许可证

私有项目，保留所有权利。
