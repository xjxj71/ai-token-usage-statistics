# Agent 数据配置指南

本文档说明各 Agent 工具的数据源路径和采集方式，以便 Token 统计采集器能够读取 Token 用量数据。

---

## 数据源路径总览

| Agent | 数据文件 | WSL 路径 | Windows UNC 路径 |
|-------|---------|---------|-----------------|
| Hermes (WSL) | state.db (SQLite) | `/root/.hermes/state.db` → 复制到 `/tmp/hermes_state.db` | `\\wsl$\project-claude\tmp\hermes_state.db` |
| Hermes (Windows) | state.db (SQLite) | — | `%LOCALAPPDATA%\hermes\state.db`（Windows 本地，直接读取） |
| Claude Code | session JSONL | `/home/claude/.claude/projects/**/*.jsonl` | `\\wsl$\project-claude\home\claude\.claude\projects\`（递归扫描） |
| OpenClaw | sessions.json | `/root/.openclaw/agents/main/sessions/sessions.json` → 复制到 `/tmp/openclaw_sessions.json` | `\\wsl$\project-claude\tmp\openclaw_sessions.json` |
| OpenClaude | session JSONL | — | `%USERPROFILE%\.openclaude\projects\**\*.jsonl`（Windows 本地，直接读取） |

### 权限与数据复制机制

Hermes 和 OpenClaw 的数据文件位于 `/root/` 目录下（权限 700），WSL 默认用户 `claude` 无法通过 UNC 路径访问。采集器使用 `wsl_copy_to_tmp()` 解决此问题：

1. 每次采集前，将源文件复制到 `/tmp/` 并设置权限为 644
2. **Windows 部署时**：通过 `wsl.exe -u root -- cp <src> /tmp/<name> && chmod 644 /tmp/<name>` 执行复制
3. **WSL 内测试时**：直接用 `shutil.copy2()` 复制（因为运行用户就是 root）

---

## 1. Claude Code（零侵入方案）

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

---

## 2. Hermes (Nous Research)

### 无需配置

Hermes 已将结构化的 Token 数据存储在 SQLite 数据库中。采集器自动读取。

### 数据位置

- **源文件**：`/root/.hermes/state.db`（需 root 权限）
- **采集副本**：`/tmp/hermes_state.db`（通过 `wsl_copy_to_tmp()` 自动复制）

### 数据格式

SQLite `sessions` 表，主要列：

| 列名 | 类型 | 说明 |
|------|------|------|
| `started_at` | REAL | Unix 时间戳 |
| `model` | TEXT | 模型名称（如 `glm-5.1`） |
| `input_tokens` | INTEGER | 输入 Token 数 |
| `output_tokens` | INTEGER | 输出 Token 数 |
| `cache_read_tokens` | INTEGER | 缓存读取 Token 数 |
| `cache_write_tokens` | INTEGER | 缓存写入 Token 数 |
| `estimated_cost_usd` | REAL | 预估费用 |
| `actual_cost_usd` | REAL | 实际费用 |
| `cost_status` | TEXT | 费用状态 |
| `billing_provider` | TEXT | 计费提供商 |
| `session_id` | TEXT | 会话 ID |

### 工作原理

`HermesCollector` 在每个轮询周期：

1. 通过 `wsl_copy_to_tmp()` 将 `/root/.hermes/state.db` 复制到 `/tmp/hermes_state.db`（chmod 644）
2. 读取副本数据库的 `sessions` 表
3. 通过追踪上次读取的 `rowid` 获取新行
4. 处理完毕后清理临时副本

### 验证数据是否存在

```bash
# 需 root 权限
sudo ls /root/.hermes/state.db
sudo sqlite3 /root/.hermes/state.db "SELECT COUNT(*) FROM sessions;"

# 检查采集副本
ls /tmp/hermes_state.db
```

---

## 2b. Hermes Windows（Nous Research — Windows 本地）

### 无需配置

Hermes 在 Windows 上运行时，`state.db` 存放在 `%LOCALAPPDATA%\hermes\` 目录下。采集器直接读取本地文件，无需 WSL 中转。

### 数据位置

- **源文件**：`%LOCALAPPDATA%\hermes\state.db`
- **访问方式**：Windows 本地直接读取，无权限问题

### 数据格式

与 WSL 版 Hermes 完全相同的 SQLite `sessions` 表结构（见上方 Hermes WSL 章节）。

### 工作原理

`HermesWindowsCollector` 继承 `HermesCollector`，复用全部核心逻辑（双模式跟踪、staleness 过滤、upsert 等），仅重写数据源获取：

1. 直接通过 `_copy_to_temp()` 将本地 `state.db` 复制到临时文件
2. 读取临时副本的 `sessions` 表（与 WSL 版完全相同的查询）
3. 以 agent 名称 `hermes-win` 写入数据库，与 `hermes`（WSL）完全隔离

### 验证数据是否存在

```cmd
:: Windows CMD
dir %LOCALAPPDATA%\hermes\state.db

:: PowerShell
Get-Item $env:LOCALAPPDATA\hermes\state.db
```

---

## 3. OpenClaw

### 无需配置

OpenClaw 将会话数据持久化为 JSON 文件，采集器自动读取。

### 数据位置

- **源文件**：`/root/.openclaw/agents/main/sessions/sessions.json`（需 root 权限）
- **采集副本**：`/tmp/openclaw_sessions.json`（通过 `wsl_copy_to_tmp()` 自动复制）

### 数据格式

`sessions.json` 是一个 JSON 对象（dict，非 list），结构如下：

```json
{
  "agent:main:main": {
    "sessionId": "abc123",
    "updatedAt": 1714617600000,
    "totalTokens": 5000,
    "inputTokens": 3000,
    "outputTokens": 2000,
    "cacheRead": 1000,
    "cacheWrite": 500,
    "estimatedCostUsd": 0.05,
    "model": "mimo-v2-pro"
  }
}
```

- **key**：agent session 名（如 `"agent:main:main"`）
- **value**：包含 `sessionId`、`updatedAt`（毫秒时间戳）、`totalTokens`、`inputTokens`、`outputTokens`、`cacheRead`、`cacheWrite`、`estimatedCostUsd`、`model` 等

### 工作原理

`OpenClawCollector` 在每个轮询周期：

1. 通过 `wsl_copy_to_tmp()` 将 `/root/.openclaw/agents/main/sessions/sessions.json` 复制到 `/tmp/openclaw_sessions.json`（chmod 644）
2. 读取副本，解析 JSON dict
3. 遍历所有 session 条目，处理 `updatedAt` 时间戳晚于上次采集的记录
4. 将新记录写入中央 SQLite 数据库

### 验证数据是否存在

```bash
# 需 root 权限
sudo ls /root/.openclaw/agents/main/sessions/sessions.json

# 检查采集副本
ls /tmp/openclaw_sessions.json
```

---

## 4. OpenClaude

### 无需配置

OpenClaude 运行在 Windows 本地，数据格式与 Claude Code 相同。采集器直接读取本地文件，无需 WSL 路径转换或权限处理。

### 数据位置

- **目录**：`%USERPROFILE%\.openclaude\projects\`
- **完整路径**：`%USERPROFILE%\.openclaude\projects\{project-name}\{session-id}.jsonl`
- **子 agent**：`%USERPROFILE%\.openclaude\projects\{project-name}\{session-id}\subagents\{agent-id}.jsonl`

### 数据格式

与 Claude Code 完全相同，每行一个 JSON 对象。采集器筛选 `type=="assistant"` 的行，提取 `message.usage` 字段。

### 工作原理

1. 递归扫描 `%USERPROFILE%\.openclaude\projects\**\*.jsonl`
2. 筛选 `type=="assistant"` 行，提取 `message.usage` 中的 token 数据
3. 通过 `file_positions` 状态文件追踪已处理的文件位置，增量读取
4. 跳过全零记录（streaming 中间块），自动计算费用

### 验证数据是否存在

```bash
# Windows CMD
dir %USERPROFILE%\.openclaude\projects\*.jsonl /s

# PowerShell
Get-ChildItem -Path $env:USERPROFILE\.openclaude\projects -Filter *.jsonl -Recurse
```

---

## 5. Token 统计工具配置

通过环境变量或 `config.py` 配置采集器：

| 变量 / 配置项 | 默认值 | 说明 |
|--------------|--------|------|
| `wsl_distro` / `TOKEN_STAT_WSL_DISTRO` | `project-claude` | WSL 发行版名称 |
| `wsl_user_accessible` | `claude` | UNC 可访问的 WSL 用户（数据可通过 UNC 读取） |
| `wsl_user_root` | `root` | root 权限用户（用于通过 `wsl.exe -u root -- cp` 复制 /root/ 下的数据） |
| `poll_interval_seconds` / `TOKEN_STAT_POLL_INTERVAL_SECONDS` | `5` | 采集器轮询间隔（秒） |
| `db_path` / `TOKEN_STAT_DB_PATH` | `data/token_statistic.db` | 本地 SQLite 数据库路径 |
| `TOKEN_STAT_HOST` | `127.0.0.1` | 服务绑定地址 |
| `TOKEN_STAT_PORT` | `8000` | 服务端口 |

### 启动示例

```bash
# Windows (PowerShell 或 CMD)
set TOKEN_STAT_WSL_DISTRO=project-claude
cd "D:\research project\ai-token-usage-statistics"
.venv\Scripts\activate
uvicorn backend.main:app --reload
```

然后在浏览器打开 http://127.0.0.1:8000 。

---

## 快速参考

| Agent | 是否需要配置 | 数据来源 | 访问方式 |
|-------|-------------|---------|---------|
| Claude Code | 无 | `~/.claude/projects/**/*.jsonl` (JSONL) | 直接读取（claude 用户自有文件） |
| Hermes (WSL) | 无 | `/root/.hermes/state.db` (SQLite) | `wsl_copy_to_tmp()` 复制到 `/tmp/` 后读取 |
| Hermes (Windows) | 无 | `%LOCALAPPDATA%\hermes\state.db` (SQLite) | Windows 本地直接读取 |
| OpenClaw | 无 | `/root/.openclaw/agents/main/sessions/sessions.json` | `wsl_copy_to_tmp()` 复制到 `/tmp/` 后读取 |
| OpenClaude | 无 | `%USERPROFILE%\.openclaude\projects\**\*.jsonl` (JSONL) | Windows 本地直接读取 |

---

## 已验证的采集结果

| Agent | 记录数 | 说明 |
|-------|--------|------|
| Hermes | 124 条 | 13 个模型，总计 44M input tokens（含 mimo-v2-pro, glm-5.1, stepfun/step-3.5-flash 等） |
| Claude Code | 2,993 条 | 零侵入方案：从 session JSONL 提取，10 个模型，覆盖 2026-03-13 ~ 2026-05-04 |
| OpenClaw | 70 条 | 模型包括 mimo-v2-pro, mimo-v2.5-pro, deepseek-v4 等 |
| OpenClaude | 78 条 | Windows 本地采集，模型 mimo-v2.5-pro，3 个 session |
