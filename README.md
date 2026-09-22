# AI Token Usage Statistics

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Svelte 5](https://img.shields.io/badge/Svelte-5-ff3e00.svg)](https://svelte.dev/)

## 截图

![Dashboard](docs/ScreenShot.png)

在 Windows / WSL 上运行的 Web 仪表盘，用于监控和可视化 WSL 中多个 AI 编程 Agent 的 Token 消耗与费用。

## 功能特性

- **多 Agent 支持**：采集 Claude Code、Hermes（WSL + Windows）、OpenClaw、OpenClaude、MimoCode、OpenCode、ZCode 的 Token 用量
- **实时仪表盘**：基于 SSE 推送更新，无需刷新页面
- **项目维度分析**：按工作目录统计各项目（repo）的 Token 消耗与费用，支持项目筛选（数据来自 claude-code / openclaude / zcode 的会话目录）
- **思考 Token 统计**：单独统计推理模型的思考（reasoning）Token，覆盖 zcode / opencode / mimocode
- **会话明细钻取**：会话级汇总列表，点击行内展开查看该会话的每条请求明细
- **环比对比**：统计卡展示较上一周期（今日→昨日同时段、7 天→前 7 天）的涨跌
- **用量报告**：一键生成日报/周报（消耗概览、Top Agent/模型/项目、套餐余量），支持复制 Markdown
- **套餐余量监控**：实时查询智谱 GLM Coding Plan、小米 MiMo Token Plan 的剩余用量（需提供浏览器 Cookie / Session Token）
- **费用估算**：内置各模型定价（YAML 配置，支持热更新），自动计算使用成本
- **人民币显示**：所有费用以人民币（¥）显示，汇率支持自动获取（含刷新按钮），支持一键从 OpenRouter 获取最新定价
- **数据管理**：明细保留策略（超期数据先按天聚合归档再删除，趋势与汇总历史永久保留）+ SQLite 自动/手动备份
- **丰富图表**：Agent Token 对比图、Agent 消耗占比饼图、模型/项目分布条形图、缓存命中率分析（ECharts）
- **时间范围筛选**：今日 / 7 天 / 30 天 / 自定义区间
- **分页与搜索**：使用记录和模型定价表支持分页（10/20/50 条）和搜索
- **可扩展采集器**：实现 `BaseCollector` 即可接入新 Agent
- **双环境运行**：Windows 原生部署（UNC 路径）和 WSL 内开发测试（自动检测）

## 系统架构

```
Windows 原生 或 WSL 内运行
┌────────────────┐    SSE     ┌──────────────────────┐
│  Svelte SPA    │◄──────────│  FastAPI Server       │
│  (浏览器)      │           │  ├─ SQLite 数据库     │
└────────────────┘           │  └─ 采集器            │
                             └────────┬─────────────-┘
                                      │ UNC / 原生路径
                             ┌────────┴──────────────┐
                             │       WSL             │
                             │  Claude Code (claude) │
                             │  Hermes (root)        │
                             │  OpenClaw (root)      │
                             └──────────────────────-┘

                             ┌────────────────────────┐
                             │     Windows 本地        │
                             │  Hermes-Win (用户)      │
                             │  OpenClaude (用户)      │
                             │  MimoCode (用户)        │
                             │  OpenCode (用户)        │
                             │  ZCode (用户)           │
                             └────────────────────────┘
```

后端设计为 Windows 原生部署，通过 UNC 路径 (`\\wsl$\project-claude\...`) 访问 WSL 中的 Agent 数据文件。在 WSL 内开发测试时也能运行——自动检测 `is_wsl` 环境变量，使用 Linux 原生路径。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11+, FastAPI, aiosqlite, Pydantic, PyYAML |
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

# Windows 原生部署
.venv\Scripts\activate
# WSL 内开发测试
source .venv/bin/activate

pip install -e ".[dev]"

# 启动服务
uvicorn backend.main:app --reload
```

> 在 WSL 内运行时会自动检测环境，使用 Linux 原生路径访问数据文件。

### 前端

```bash
cd frontend
npm install
npm run dev        # 开发服务器
npm run build      # 生产构建（由 FastAPI 托管）
```

### 配置项

通过环境变量或 `config.py` 配置（前缀 `TOKEN_STAT_`）：

| 变量 / 配置项 | 默认值 | 说明 |
|--------------|--------|------|
| `wsl_distro` / `TOKEN_STAT_WSL_DISTRO` | `project-claude` | WSL 发行版名称 |
| `wsl_user_accessible` / `TOKEN_STAT_WSL_DISTRO` | `claude` | UNC 可访问的 WSL 用户（数据可通过 UNC 读取） |
| `wsl_user_root` / `TOKEN_STAT_WSL_USER_ROOT` | `root` | root 权限用户（用于通过 `wsl.exe -u root -- cp` 复制 /root/ 下的数据） |
| `poll_interval_seconds` / `TOKEN_STAT_POLL_INTERVAL_SECONDS` | `5` | 采集器轮询间隔（秒） |
| `db_path` / `TOKEN_STAT_DB_PATH` | `data/token_statistic.db` | 本地 SQLite 数据库路径 |
| `TOKEN_STAT_HOST` | `127.0.0.1` | 服务绑定地址 |
| `TOKEN_STAT_PORT` | `8001` | 服务端口 |
| `TOKEN_STAT_API_KEY` | 空 | API 鉴权密钥；为空时只允许本机访问。设置后所有 `/api/` 请求需携带 `X-API-Key` 请求头 |
| `TOKEN_STAT_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | CORS 允许的来源（逗号分隔，生产环境请设置为实际域名） |
| `TOKEN_STAT_USD_TO_CNY_RATE` | `7.25` | 汇率回退值（实时汇率自动拉取失败、且无上次成功值时使用） |
| `TOKEN_STAT_RETENTION_DAYS` | `0` | 明细保留天数（`0` = 永久保留）。超期明细先按天聚合进 `usage_daily` 再删除；也可在前端"数据管理"面板在线修改 |
| `TOKEN_STAT_BACKUP_KEEP` | `10` | 备份文件保留个数 |
| `TOKEN_STAT_AUTO_BACKUP` | `true` | 是否每日自动备份到 `data/backups/` |
| `TOKEN_STAT_ZHIPU_SESSION_TOKEN` | — | 智谱 Coding Plan 的 Session Token |
| `TOKEN_STAT_XIAOMI_COOKIE` | — | 小米 MiMo Token Plan 的完整 Cookie |

> **套餐凭据配置**：智谱/小米的凭据也可写在 `config/quota_providers.yaml`（从 [`config/quota_providers.example.yaml`](config/quota_providers.example.yaml) 复制模板填写）。该文件包含敏感凭据，已被 `.gitignore` 忽略，**切勿提交到仓库**。

### 数据源路径

| Agent | 数据文件 | WSL 路径 | Windows 路径 |
|-------|---------|---------|-------------|
| Hermes (WSL) | state.db (SQLite) | `/root/.hermes/state.db` → 复制到 `/tmp/hermes_state.db` | `\\wsl$\project-claude\tmp\hermes_state.db` |
| Hermes (Windows) | state.db (SQLite) | — | `%LOCALAPPDATA%\hermes\state.db`（Windows 本地，直接读取） |
| Claude Code | session JSONL | `/home/claude/.claude/projects/**/*.jsonl` | `\\wsl$\project-claude\home\claude\.claude\projects\`（递归扫描） |
| OpenClaw | sessions.json | `/root/.openclaw/agents/main/sessions/sessions.json` → 复制到 `/tmp/openclaw_sessions.json` | `\\wsl$\project-claude\tmp\openclaw_sessions.json` |
| OpenClaude | session JSONL | — | `%USERPROFILE%\.openclaude\projects\**\*.jsonl`（Windows 本地，直接读取） |
| MimoCode | mimocode.db (SQLite) | — | `~/.local/share/mimocode/mimocode.db`（Windows 本地，直接读取） |
| OpenCode | opencode.db (SQLite) | — | `~/.local/share/opencode/opencode.db`（Windows 本地，直接读取） |
| ZCode | db.sqlite (SQLite) | — | `~/.zcode/cli/db/db.sqlite`（Windows 本地，快照后读取） |

> **权限说明**：Hermes（WSL）和 OpenClaw 的数据在 `/root/` 下（权限 700），WSL 默认用户 `claude` 无法通过 UNC 访问。采集器会在每次采集前通过 `wsl_copy_to_tmp()` 将文件复制到 `/tmp/`（chmod 644），然后读取副本。Windows 部署时用 `wsl.exe -u root -- cp` 执行复制；WSL 内测试时直接用 `shutil.copy2`。Claude Code 的数据在 `claude` 用户目录下，无权限问题。Hermes（Windows）的数据在 `%LOCALAPPDATA%` 下，当前用户直接可读。

### Agent 配置

- **Hermes (WSL)** 和 **OpenClaw**：无需配置，采集器自动读取数据文件。
- **Hermes (Windows)**：无需配置，采集器直接读取 `%LOCALAPPDATA%\hermes\state.db`。与 WSL 版采集器独立运行，agent 名称为 `hermes-win`，互不干扰。
- **Claude Code**：无需配置。采集器扫描 `~/.claude/projects/` 下所有 session JSONL 文件，提取 `message.usage` 中的 token 数据。零侵入，无需在 Claude Code 中做任何操作。
- **OpenClaude**：无需配置。采集器扫描 Windows 本地 `%USERPROFILE%\.openclaude\projects\` 下所有 session JSONL 文件，数据格式与 Claude Code 相同。无需 WSL 路径转换或权限处理。
- **MimoCode**：无需配置。采集器读取 `~/.local/share/mimocode/mimocode.db` SQLite 数据库，从 `message` 表提取 assistant 消息的 token 使用数据。
- **OpenCode**：无需配置。采集器读取 `~/.local/share/opencode/opencode.db` SQLite 数据库，数据格式与 MimoCode 相同（MiMoCode 是 OpenCode 的 fork）。
- **ZCode**：无需配置。采集器读取 `~/.zcode/cli/db/db.sqlite` 的 `model_usage` 表（每次模型请求一行，token 字段完整）。数据库为 WAL 模式且被 ZCode 持续写入，采集时会先复制主库 + WAL 副本再查询；进行中的请求在完成后自动补收。

详见 [Agent 配置指南](docs/agent-setup-guide.md)。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/summary` | 汇总统计，含按 Agent/模型/项目的明细；`compare=true` 附带上一周期总量 |
| GET | `/api/usage` | 分页查询使用记录（支持 `session_id`、`project` 过滤） |
| GET | `/api/sessions` | 会话级汇总列表（按 Agent × 会话聚合，分页） |
| GET | `/api/agents` | 获取已追踪的 Agent 列表 |
| GET | `/api/projects` | 获取出现过的项目名列表（供筛选） |
| GET | `/api/models` | 获取模型列表及定价 |
| GET | `/api/config` | 获取前端配置（生效汇率及来源） |
| POST | `/api/config/exchange-rate/refresh` | 强制刷新实时汇率（仅本机或携带 API Key） |
| GET | `/api/report` | 用量报告（汇总 + 环比 + Top 榜 + 套餐余量 + Markdown 文本） |
| GET | `/api/stream` | SSE 实时推送流 |
| GET | `/api/pricing` | 获取所有模型定价 |
| PUT | `/api/pricing/{model}` | 更新指定模型定价 |
| POST | `/api/pricing/refresh` | 从 OpenRouter 一键更新所有模型定价 |
| GET | `/api/quota` | 获取所有已启用套餐的余量快照（带缓存） |
| POST | `/api/quota/refresh` | 强制刷新套餐余量 |
| GET | `/api/quota/providers` | 列出已配置的套餐 Provider 及启用状态 |
| PUT | `/api/quota/config` | 更新套餐 Provider 配置（session token、套餐等级、启用开关） |
| GET | `/api/config/data` | 获取数据管理设置（保留天数、备份策略） |
| PUT | `/api/config/data` | 更新数据管理设置（仅本机或携带 API Key） |
| POST | `/api/maintenance/cleanup` | 立即执行一次数据保留清理（仅本机或携带 API Key） |
| POST | `/api/backup` | 立即创建数据库备份（仅本机或携带 API Key） |
| GET | `/api/backups` | 列出备份文件 |
| GET | `/api/backups/{name}` | 下载备份文件 |
| DELETE | `/api/backups/{name}` | 删除备份文件（仅本机或携带 API Key） |

### 请求示例

```bash
# 今日汇总（按北京时间 0 点起算）
curl "http://localhost:8001/api/summary?range=today"

# 按 Agent 和模型筛选
curl "http://localhost:8001/api/summary?range=7d&agent=claude-code&model=claude-sonnet-4-6"

# 最近使用记录（支持 range 参数）
curl "http://localhost:8001/api/usage?range=today&page=1&limit=50"

# 不指定 range 时按 from/to 筛选
curl "http://localhost:8001/api/usage?from=2026-05-01&to=2026-05-07"
```

> **时区说明**：`range=today`、`7d`、`30d` 均按本地时区（Asia/Shanghai）计算零点起止时间，数据库中存储的 timestamp 为 UTC 格式。前端同样使用本地日期生成 from/to 参数，确保跨时区一致性。

## 项目结构

```
ai-token-usage-statistics/
├── backend/
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # pydantic-settings 配置
│   ├── exchange_rate.py     # USD→CNY 汇率（自动获取 + 缓存 + 回退）
│   ├── maintenance.py       # 数据保留（聚合归档）与备份
│   ├── api/                 # REST + SSE 接口（summary/usage/sessions/report/maintenance 等）
│   ├── collectors/          # 各 Agent 数据采集器
│   ├── db/                  # SQLite 连接、表结构与迁移
│   ├── pricing/             # 模型定价与费用计算
│   └── quota/               # 套餐余量监控（Zhipu、Xiaomi）
├── frontend/
│   └── src/
│       ├── App.svelte       # 主应用组件
│       ├── components/      # StatCard, ProjectBar, SessionTable, ReportCard, DataManagement 等
│       ├── api/             # 请求封装 + SSE 客户端 + 参数构造
│       └── types/           # TypeScript 类型定义
├── tests/                   # pytest 测试用例
├── config/                  # 模型定价 YAML + 套餐 Provider 配置
├── scripts/                 # 工具脚本（费用重算等）
├── docs/                    # 设计文档、配置指南
└── pyproject.toml           # Python 项目配置
```

### 数据保留与备份说明

- **保留策略**：`retention_days > 0` 时，超过保留期的使用明细会先按 天×Agent×模型×项目 聚合进 `usage_daily` 表再删除。趋势图、汇总统计、缓存率分析会自动 UNION 归档数据，**完整历史不丢失**；只有"使用记录 / 会话明细"超过保留期后不可见。归档后修改模型定价仍会影响历史费用显示（按归档的 token 数重算）。
- **备份**：每日自动（可关）+ 手动备份，存放在 `data/backups/`，保留最新 N 个。**恢复方法**：停止后端服务，用备份文件替换 `data/token_statistic.db`，重新启动即可。
- **旧库升级**：首次启动新版本时自动执行迁移——为历史记录从 `raw_data` 回填 `project`（取会话工作目录最后一段）与 `reasoning_tokens` 列，无需手动操作。

### 安全提示

- `config/quota_providers.yaml` 含上游会话凭据，已被 `.gitignore` 忽略，**切勿提交**。若曾提交过该文件，请立即轮换智谱 / 小米凭据，并视情况清理 git 历史。
- 默认只监听 `127.0.0.1`。若绑定到 `0.0.0.0` 或放在反向代理后，请设置 `TOKEN_STAT_API_KEY`，并为写入类接口与备份下载启用鉴权。

## 测试

```bash
# 运行全部测试
pytest

# 带覆盖率报告
pytest -q

# 代码检查
ruff check backend/ tests/
```

## 许可证

[MIT License](LICENSE)
