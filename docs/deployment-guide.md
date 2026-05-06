# 部署文档

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.11+ | 后端运行时 |
| Node.js | 18+ | 前端构建 |
| WSL 2 | - | 已安装至少一个 AI Agent（Claude Code / Hermes / OpenClaw） |
| Windows | 10/11 | 支持 `\\wsl$` UNC 路径 |

## 目录结构

```
ai-token-usage-statistics/
├── backend/           # FastAPI 后端
├── frontend/          # Svelte 前端源码
├── data/              # SQLite 数据库（运行时生成）
├── config/            # 模型定价 YAML 配置
├── scripts/           # 工具脚本（费用重算等）
├── docs/              # 文档
├── tests/             # 测试
└── pyproject.toml     # Python 项目配置
```

## 一、后端部署

### 1. 创建虚拟环境

```bash
cd /path/to/ai-token-usage-statistics
python -m venv .venv
```

- Windows CMD：`.venv\Scripts\activate.bat`
- Windows PowerShell：`.venv\Scripts\Activate.ps1`
- WSL 内开发测试：`source .venv/bin/activate`

> 后端设计为 Windows 原生部署，通过 UNC 路径 (`\\wsl$\project-claude\...`) 监控 WSL 中的 AI Agent。在 WSL 内开发测试时也能运行——自动检测 `is_wsl` 环境，使用 Linux 原生路径。

### 2. 安装依赖

```bash
pip install -e .
```

开发环境额外安装：

```bash
pip install -e ".[dev]"
```

### 3. 配置环境变量

所有配置项通过环境变量设置，前缀为 `TOKEN_STAT_`，或直接在 `config.py` 中修改默认值：

| 变量 / 配置项 | 默认值 | 说明 |
|--------------|--------|------|
| `TOKEN_STAT_WSL_DISTRO` / `wsl_distro` | `project-claude` | WSL 发行版名称 |
| `wsl_user_accessible` | `claude` | UNC 可访问的 WSL 用户（数据可通过 UNC 读取） |
| `wsl_user_root` | `root` | root 权限用户（用于通过 `wsl.exe -u root -- cp` 复制 /root/ 下的数据） |
| `TOKEN_STAT_POLL_INTERVAL_SECONDS` / `poll_interval_seconds` | `5` | 采集器轮询间隔（秒） |
| `TOKEN_STAT_HOST` | `127.0.0.1` | 服务绑定地址 |
| `TOKEN_STAT_PORT` | `8000` | 服务端口 |
| `TOKEN_STAT_DB_PATH` / `db_path` | `data/token_statistic.db` | SQLite 数据库路径 |

可在启动前设置，或写入 `.env` 文件（需要额外安装 python-dotenv）：

```bash
# Linux/WSL
export TOKEN_STAT_WSL_DISTRO=project-claude
export TOKEN_STAT_PORT=***

# Windows CMD
set TOKEN_STAT_WSL_DISTRO=project-claude
set TOKEN_STAT_PORT=***

# Windows PowerShell
$env:TOKEN_STAT_WSL_DISTRO="project-claude"
$env:TOKEN_STAT_PORT="***"
```

### 4. 启动服务

#### 开发模式（热重载）

```bash
uvicorn backend.main:app --reload
```

默认监听 `http://127.0.0.1:8000`。自定义地址和端口：

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 9000
```

#### 生产模式

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

> 注意：由于使用了 SQLite 和内存状态（采集器），建议单 worker 运行。如需多 worker，需切换到外部数据库（如 PostgreSQL）并使用 Redis 管理采集器状态。

## 二、前端部署

### 1. 安装依赖

```bash
cd frontend
npm install
```

### 2. 开发模式

```bash
npm run dev
```

启动 Vite 开发服务器（默认 `http://localhost:5173`），自动代理 `/api` 请求到后端 8000 端口。

> **WSL 性能提示**：如果项目位于 `/mnt/` 下的 Windows 磁盘，Vite 启动和热更新会较慢。可将前端代码复制到 WSL 本地文件系统（如 `/tmp/`）运行以获得正常速度。

### 3. 生产构建

```bash
npm run build
```

构建产物输出到 `frontend/dist/`。FastAPI 会自动检测此目录并托管静态文件，无需单独部署前端服务器。

生产环境下只需启动后端，浏览器直接访问 `http://127.0.0.1:8000` 即可。

## 三、Agent 数据采集配置

### 数据源路径总览

| Agent | 数据文件 | WSL 路径 | Windows UNC 路径 |
|-------|---------|---------|-----------------|
| Hermes | state.db (SQLite) | `/root/.hermes/state.db` → 复制到 `/tmp/hermes_state.db` | `\\wsl$\project-claude\tmp\hermes_state.db` |
| Claude Code | session JSONL | `/home/claude/.claude/projects/**/*.jsonl` | `\\wsl$\project-claude\home\claude\.claude\projects\`（递归扫描） |
| OpenClaw | sessions.json | `/root/.openclaw/agents/main/sessions/sessions.json` → 复制到 `/tmp/openclaw_sessions.json` | `\\wsl$\project-claude\tmp\openclaw_sessions.json` |

### 权限与数据复制机制

Hermes 和 OpenClaw 的数据文件位于 `/root/` 目录下（权限 700），WSL 默认用户 `claude` 无法通过 UNC 路径访问。采集器使用 `wsl_copy_to_tmp()` 解决此问题：

1. 每次采集前，将源文件复制到 `/tmp/` 并设置权限为 644
2. **Windows 部署时**：通过 `wsl.exe -u root -- cp <src> /tmp/<name> && chmod 644 /tmp/<name>` 执行复制
3. **WSL 内测试时**：直接用 `shutil.copy2()` 复制（因为运行用户就是 root）

### Claude Code（零侵入方案）

**无需配置，无需在 Claude Code 中做任何操作。**

数据位置：
- WSL 路径: `~/.claude/projects/` 下按项目组织的 JSONL 文件
- 完整路径: `/home/claude/.claude/projects/{project-name}/{session-id}.jsonl`
- Windows UNC: `\\wsl$\project-claude\home\claude\.claude\projects\`
- 无权限问题（claude 用户自己的文件）

数据格式：
每行一个 JSON 对象。采集器筛选 `type=="assistant"` 的行，提取 `message.usage` 字段：

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-opus-4-6",
    "usage": {
      "input_tokens": 5000,
      "output_tokens": 800,
      "cache_read_input_tokens": 20000,
      "cache_creation_input_tokens": 1000
    }
  },
  "timestamp": "2026-05-02T10:30:00.123Z",
  "sessionId": "abc123",
  "cwd": "/home/claude/project",
  "gitBranch": "main"
}
```

工作原理：
1. 递归扫描 `~/.claude/projects/**/*.jsonl`
2. 筛选 `type=="assistant"` 行，提取 `message.usage` 中的 token 数据
3. 通过 `file_positions` 状态文件追踪已处理的文件位置，增量读取
4. 自动计算费用（基于 `config/model_pricing.yaml`）

验证：

```bash
# 查看 session JSONL 文件
find ~/.claude/projects -name "*.jsonl" | head -5

# 查看某文件中的 token 数据
cat ~/.claude/projects/*/*.jsonl | grep '"type":"assistant"' | head -1 | python3 -m json.tool
```

### Hermes

无需配置。采集器自动读取 `/root/.hermes/state.db`（通过复制到 `/tmp/hermes_state.db` 后访问）。

数据格式：SQLite `sessions` 表，包含 `started_at`（REAL Unix 时间戳）、`model`、`input_tokens`、`output_tokens`、`cache_read_tokens` 等列。

验证：

```bash
# 需 root 权限
sudo ls /root/.hermes/state.db
sudo sqlite3 /root/.hermes/state.db "SELECT COUNT(*) FROM sessions;"
```

### OpenClaw

无需配置。采集器自动读取 `/root/.openclaw/agents/main/sessions/sessions.json`（通过复制到 `/tmp/openclaw_sessions.json` 后访问）。

数据格式：JSON 对象（dict，非 list），key 为 agent session 名如 `"agent:main:main"`，value 包含 `sessionId`、`updatedAt`（毫秒时间戳）、`totalTokens`、`inputTokens`、`outputTokens`、`cacheRead`、`cacheWrite`、`estimatedCostUsd`、`model` 等。

验证：

```bash
# 需 root 权限
sudo ls /root/.openclaw/agents/main/sessions/sessions.json

# 或检查复制后的副本
ls /tmp/openclaw_sessions.json
```

## 四、模型定价配置

模型定价数据存储在 `config/model_pricing.yaml` 中。修改定价后：

1. **热更新（无需重启）**：调用 `backend.pricing.model_pricing.reload_pricing()`
2. **重算历史费用**：运行 `python scripts/recalc_costs.py`（支持 `--dry-run` 预览）

配置文件格式：

```yaml
models:
  claude-opus-4-6:
    input: 15.0      # 每百万 token 输入价格 (USD)
    output: 75.0     # 每百万 token 输出价格 (USD)
    cache_read: 1.875  # 可选，默认 0
    cache_write: 18.75  # 可选，默认 0
  # 免费模型
  deepseek/deepseek-v4-flash-free:
    input: 0
    output: 0
```

## 五、数据库

### 自动初始化

首次启动后端时，自动在 `data/` 目录下创建 SQLite 数据库（`token_statistic.db`），包括：

- `token_usage` 表：存储采集到的 Token 使用记录
- `model_pricing` 表：存储模型定价数据（首次启动时自动填充）
- 相关索引

### 数据位置

默认：`data/token_statistic.db`（相对于项目根目录）。

可通过 `TOKEN_STAT_DB_PATH` 环境变量修改为绝对路径。

### 备份

```bash
# 安全备份（SQLite 内置）
sqlite3 data/token_statistic.db ".backup data/backup_$(date +%Y%m%d).db"
```

建议配置定时任务（如 crontab 或 Windows 任务计划程序）每日自动备份。

### 数据清理

```sql
-- 删除 90 天前的记录
DELETE FROM token_usage WHERE timestamp < datetime('now', '-90 days');
```

## 六、系统服务（可选）

### Linux systemd

创建 `/etc/systemd/system/ai-token-stat.service`：

```ini
[Unit]
Description=AI Token Usage Statistics
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/ai-token-usage-statistics
Environment=TOKEN_STAT_WSL_DISTRO=project-claude
ExecStart=/path/to/ai-token-usage-statistics/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-token-stat
sudo systemctl start ai-token-stat
```

### Windows 任务计划程序

1. 打开"任务计划程序"
2. 创建基本任务，触发器选"计算机启动时"
3. 操作选"启动程序"：
   - 程序：`D:\research project\ai-token-usage-statistics\.venv\Scripts\uvicorn.exe`
   - 参数：`backend.main:app --host 127.0.0.1 --port 8000`
   - 起始于：`D:\research project\ai-token-usage-statistics`
4. 添加环境变量 `TOKEN_STAT_WSL_DISTRO=project-claude`

## 七、验证部署

### 1. 检查后端 API

```bash
# 健康检查（汇总接口）
curl http://127.0.0.1:8000/api/summary?range=today

# Agent 列表
curl http://127.0.0.1:8000/api/agents

# 模型列表
curl http://127.0.0.1:8000/api/models

# API 文档
# 浏览器打开 http://127.0.0.1:8000/docs
```

### 2. 检查前端

浏览器打开 `http://127.0.0.1:8000`（生产模式）或 `http://localhost:5173`（开发模式），应看到仪表盘页面。

### 3. 检查数据采集

在 WSL 中运行任意 Agent 执行操作，等待数秒后刷新仪表盘，确认数据更新。

### 4. 检查 SSE 实时推送

打开浏览器开发者工具 → Network → EventStream，应能看到 `/api/stream` 的持续连接。

## 八、常见问题

### 前端页面空白

确认 `frontend/dist/` 目录存在且包含构建产物。运行 `cd frontend && npm run build` 重新构建。

### 采集器无数据

1. 确认 WSL 中 Agent 已正常运行并产生数据
2. 确认 `TOKEN_STAT_WSL_DISTRO` 与实际 WSL 发行版名称匹配（在 CMD 中运行 `wsl -l -v` 查看，默认：`project-claude`）
3. 如果 Hermes 或 OpenClaw 无数据，检查 `wsl_copy_to_tmp()` 是否成功：在 WSL 中运行 `ls /tmp/hermes_state.db` 和 `ls /tmp/openclaw_sessions.json`
4. 检查 Windows 能否通过 UNC 路径访问 WSL 文件：在资源管理器地址栏输入 `\\wsl$\project-claude\home\claude\`

### 端口被占用

```bash
# 查看占用端口的进程
# Linux/WSL
ss -tlnp | grep 8000
# Windows
netstat -ano | findstr 8000
```

更换端口：`TOKEN_STAT_PORT=9000 uvicorn backend.main:app`

### SQLite 数据库锁定

确保没有多个进程同时写入数据库。本项目使用 WAL 模式（`PRAGMA journal_mode=WAL`），支持并发读写，但仍建议单实例运行。

### WSL 跨磁盘 IO 慢

如果项目放在 Windows 磁盘（如 `/mnt/d/`），文件读写性能会显著下降。解决方案：

1. **开发模式**：将前端代码复制到 WSL 本地文件系统（`/tmp/` 或 `~/`）运行
2. **生产模式**：前端构建后由后端托管，不受此影响

## 九、升级

```bash
# 1. 拉取最新代码
git pull

# 2. 更新 Python 依赖
pip install -e ".[dev]"

# 3. 重新构建前端
cd frontend && npm install && npm run build && cd ..

# 4. 重启服务
# systemd
sudo systemctl restart ai-token-stat
# 或直接重启 uvicorn
```

数据库 schema 变更通过 `CREATE TABLE IF NOT EXISTS` 和 `CREATE INDEX IF NOT EXISTS` 自动处理，无需手动迁移。
