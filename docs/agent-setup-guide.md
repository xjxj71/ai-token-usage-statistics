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
| Codex | session JSONL | — | `%USERPROFILE%\.codex\sessions\YYYY\MM\DD\rollout-*.jsonl`（Windows 本地，直接读取） |
| Qoder（国际版） | qodercli.log + 会话 JSONL | — | `%USERPROFILE%\.qoder\logs\runs\*\qodercli.log`、`%USERPROFILE%\.qoder\projects\**\*.jsonl`（Windows 本地，直接读取） |

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

## 5. ZCode

### 无需配置

ZCode CLI 在本地 SQLite 数据库中记录每次模型请求的完整 token 用量，采集器直接轮询读取，零侵入。

### 数据位置

- **数据库**：`~/.zcode/cli/db/db.sqlite`（WAL 模式，ZCode 运行期间持续写入）
- **核心表**：`model_usage` — 每次模型请求一行，含 `input_tokens` / `output_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens` / `reasoning_tokens`、`model_id`、`started_at` / `completed_at`（epoch 毫秒）

### 工作原理

1. mtime/size 快路径：主库与 WAL 文件均未变化时跳过本轮轮询
2. 复制主库 + `-wal`/`-shm` 副本到临时文件（`sqlite_utils.copy_sqlite_with_wal()`），避免与 ZCode 的写入争锁
3. 以 `completed_at`（epoch 毫秒）为水位增量查询：进行中的请求（token 未定稿）在完成后的下一轮自动补收
4. 子代理（如 `zcode-Explore`）与后台请求（如会话标题生成）均计入 `zcode` 名下，详情记录在 `raw_data`（turn_id、query_source、项目路径等）

### 验证数据是否存在

```bash
# Windows PowerShell
Get-Item $env:USERPROFILE\.zcode\cli\db\db.sqlite

# 查看用量记录数
sqlite3 "$env:USERPROFILE\.zcode\cli\db\db.sqlite" "SELECT COUNT(*) FROM model_usage"
```

---

## 5b. Codex

### 无需配置

Codex CLI 把每个会话写成一个追加式 rollout JSONL，采集器直接轮询读取，零侵入。

### 数据位置

- **会话目录**：`~/.codex/sessions/YYYY/MM/DD/rollout-<时间戳>-<会话UUID>.jsonl`（Windows 本地）
- **用量事件**：每次模型响应一条 `token_usage_record`（顶层 `type`），`usage` 内含 `input_tokens` / `cached_input_tokens` / `cache_write_input_tokens` / `output_tokens` / `reasoning_output_tokens`
- **上下文**：`session_meta`（会话 id、cwd、CLI 版本）与 `turn_context`（模型、cwd）行

### 工作原理

1. 按文件字节偏移水位增量读取（与 Claude Code / OpenClaude 相同机制），半行写入的尾部留待下一轮
2. 每个文件的 session_id / cwd / 模型上下文缓存在采集器状态里，增量续读时仍能正确归属项目与模型
3. token 口径转换：Codex 的 `input_tokens` 含缓存命中（OpenAI 口径），入库时拆为「未缓存输入 + 缓存读取」两列；`reasoning_output_tokens` 计入思考 Token
4. 兜底：旧版 CLI 无 `token_usage_record` 时解析 `event_msg/token_count` 的 `last_token_usage`；同一文件两种事件不重复计数
5. 会话 id 优先取自文件名中的 UUID，即使从文件中间续读也能关联会话

### 验证数据是否存在

```powershell
# Windows PowerShell
Get-ChildItem "$env:USERPROFILE\.codex\sessions" -Recurse -Filter *.jsonl | Measure-Object

# 查看用量事件条数（任选一个文件）
Select-String -Path (Get-ChildItem "$env:USERPROFILE\.codex\sessions" -Recurse -Filter *.jsonl | Select-Object -First 1).FullName -Pattern 'token_usage_record' | Measure-Object
```

---

## 5c. Qoder（国际版）

### 无需配置

Qoder 桌面客户端（国际版）把数据写在 `~/.qoder/`（国内版在 `~/.qoder-cn`，暂不支持），采集器直接轮询读取，零侵入。客户端安装位置（如 `F:\Qoder`）只存放程序本体，用量数据始终在用户目录下。

### 数据位置

- **运行日志**：`~/.qoder/logs/runs/<run_id>/qodercli.log` —— 每次工具权限检查的 `[permission-check] ... context={"messages":[...]}` 行会转储当前请求上下文，其中 assistant 消息带 `message.usage`（每次模型请求的完整 token 记录：`input_tokens` / `output_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens`）
- **会话转录**：`~/.qoder/projects/**/*.jsonl` —— Claude Code 风格的会话文件；压缩（compact）事件带 `compactUsage`（compaction 请求的真实用量），并提供 会话 id → 工作目录 的映射
- **模型名**：消息内 `model` 可能是路由别名 `auto`，此时取用户事件的 `businessModelKey`（如 `kmodel_latest`）或转录 `runtime-config` 事件的 `model`

### 工作原理

1. 运行日志：以「`"usage":` + `"type":"assistant"`」子串粗筛行，按 assistant 消息 uuid 去重——同一响应会在后续每次工具调用的上下文转储里重复出现
2. 会话转录：按事件结构解析（非文本匹配）建立 `sessionId → cwd` 映射，供日志记录做项目归属；compact 事件按 uuid 去重
3. token 口径转换：Qoder 的 `input_tokens` 为含缓存的提示词总量（`context_usage_ratio == input_tokens / 窗口`，OpenAI 口径），入库时拆为「未缓存输入 + 缓存读取 + 缓存写入」
4. 按文件字节偏移水位增量读取；半行写入的尾部留待下一轮；文件被截断/替换时水位自动归零

### 已知盲区（有意不计）

- 转录落盘时会剥离 `message.usage`（1.1.86 实测），会话状态文件的用量段是加密的——本地明文用量只存在于运行日志的上下文转储与 compact 事件中
- `turn.finished` / `fork.agent.completed` 事件的 token 字段当前版本恒为 0；即使未来填实，其语义是整轮聚合，计入会与逐请求记录重复
- 纯对话、无工具调用的请求若未触发权限检查，其响应不会出现在任何上下文转储里，本地无明文用量可采

### 验证数据是否存在

```powershell
# Windows PowerShell：运行日志中的用量转储行数
Get-ChildItem "$env:USERPROFILE\.qoder\logs\runs" -Recurse -Filter qodercli.log | ForEach-Object { (Select-String -Path $_.FullName -Pattern '"usage":').Count }

# 会话转录中的 compact 用量事件
Get-ChildItem "$env:USERPROFILE\.qoder\projects" -Recurse -Filter *.jsonl | ForEach-Object { (Select-String -Path $_.FullName -Pattern 'compactUsage').Count }
```

---

## 6. Token 统计工具配置

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
| MimoCode | 无 | `~/.local/share/mimocode/mimocode.db` (SQLite) | Windows 本地直接读取 |
| OpenCode | 无 | `~/.local/share/opencode/opencode.db` (SQLite) | Windows 本地直接读取 |
| Hanako | 无 | `~/.hanako/agents/hanako/sessions/**/*.jsonl` (JSONL) | Windows 本地直接读取 |
| ZCode | 无 | `~/.zcode/cli/db/db.sqlite` 的 `model_usage` 表 (SQLite) | 复制主库 + WAL 副本后读取 |
| Codex | 无 | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` (JSONL) | Windows 本地直接读取 |
| Qoder（国际版） | 无 | `~/.qoder/logs/runs/*/qodercli.log` + `~/.qoder/projects/**/*.jsonl` | Windows 本地直接读取 |

---

## 已验证的采集结果

| Agent | 记录数 | 说明 |
|-------|--------|------|
| Hermes | 124 条 | 13 个模型，总计 44M input tokens（含 mimo-v2-pro, glm-5.1, stepfun/step-3.5-flash 等） |
| Claude Code | 2,993 条 | 零侵入方案：从 session JSONL 提取，10 个模型，覆盖 2026-03-13 ~ 2026-05-04 |
| OpenClaw | 70 条 | 模型包括 mimo-v2-pro, mimo-v2.5-pro, deepseek-v4 等 |
| OpenClaude | 78 条 | Windows 本地采集，模型 mimo-v2.5-pro，3 个 session |
| ZCode | 226 条 | Windows 本地采集，`model_usage` 表直读，模型 glm-5.3，覆盖 2026-08-29 |
| Qoder | 9 条 | Windows 本地采集（国际版），7 条逐请求（权限检查转储）+ 2 条 compact，模型 kmodel_latest，覆盖 2026-11-23 |
