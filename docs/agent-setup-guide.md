# Agent 数据配置指南

本文档说明各 Agent 工具的数据源路径和采集方式，以便 Token 统计采集器能够读取 Token 用量数据。

---

## 数据源路径总览

| Agent | 数据文件 | WSL 路径 | Windows UNC 路径 |
|-------|---------|---------|-----------------|
| Hermes | state.db (SQLite) | `/root/.hermes/state.db` → 复制到 `/tmp/hermes_state.db` | `\\wsl$\project-claude\tmp\hermes_state.db` |
| Claude Code | costs.jsonl (JSONL) | `/home/claude/.claude/metrics/costs.jsonl` | `\\wsl$\project-claude\home\claude\.claude\metrics\costs.jsonl` |
| OpenClaw | sessions.json | `/root/.openclaw/agents/main/sessions/sessions.json` → 复制到 `/tmp/openclaw_sessions.json` | `\\wsl$\project-claude\tmp\openclaw_sessions.json` |

### 权限与数据复制机制

Hermes 和 OpenClaw 的数据文件位于 `/root/` 目录下（权限 700），WSL 默认用户 `claude` 无法通过 UNC 路径访问。采集器使用 `wsl_copy_to_tmp()` 解决此问题：

1. 每次采集前，将源文件复制到 `/tmp/` 并设置权限为 644
2. **Windows 部署时**：通过 `wsl.exe -u root -- cp <src> /tmp/<name> && chmod 644 /tmp/<name>` 执行复制
3. **WSL 内测试时**：直接用 `shutil.copy2()` 复制（因为运行用户就是 root）

---

## 1. Claude Code

### 无需额外配置

Claude Code 自动在 `~/.claude/metrics/` 目录下生成 `costs.jsonl` 文件，采集器直接读取该文件。

### 数据格式

JSONL 文件，每行一个 JSON 对象：

```json
{
  "timestamp": "2026-05-02T10:30:00.123456+00:00",
  "session_id": "abc123",
  "model": "unknown",
  "input_tokens": 0,
  "output_tokens": 0,
  "estimated_cost_usd": 0.0
}
```

> **注意**：当前 `costs.jsonl` 全是零数据（model=unknown, tokens=0），属于占位采集，等待 Claude Code 后续版本提供有效数据。

### 采集器工作原理

`ClaudeCodeCollector` 每 5 秒轮询 `costs.jsonl` 文件（Windows 通过 UNC 路径 `\\wsl$\project-claude\home\claude\.claude\metrics\costs.jsonl`，WSL 内直接读取 `/home/claude/.claude/metrics/costs.jsonl`），解析新增的 JSONL 行，计算费用，写入中央 SQLite 数据库。增量读取通过文件偏移量追踪实现。

### 验证

```bash
# 检查数据文件是否存在
ls ~/.claude/metrics/costs.jsonl

# 查看内容
head -5 ~/.claude/metrics/costs.jsonl
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

## 4. Token 统计工具配置

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
| Claude Code | 无 | `~/.claude/metrics/costs.jsonl` (JSONL) | UNC 或原生路径直接读取 |
| Hermes | 无 | `/root/.hermes/state.db` (SQLite) | `wsl_copy_to_tmp()` 复制到 `/tmp/` 后读取 |
| OpenClaw | 无 | `/root/.openclaw/agents/main/sessions/sessions.json` | `wsl_copy_to_tmp()` 复制到 `/tmp/` 后读取 |

---

## 已验证的采集结果

| Agent | 记录数 | 说明 |
|-------|--------|------|
| Hermes | 71 条 | 模型 glm-5.1，input_tokens 最高 28,654 |
| Claude Code | 102 条 | 全是零数据（costs.jsonl 本身无有效数据） |
| OpenClaw | 70 条 | 模型包括 mimo-v2-pro, mimo-v2.5-pro, deepseek-v4 等 |
