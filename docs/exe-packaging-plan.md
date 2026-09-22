# Windows 桌面化（exe 安装包）实施方案

> 状态：**实现规格已补齐，待编码**（本文档即实施依据）  
> 日期：2026-09-19 初稿 · 2026-09-22 补齐路径/生命周期/构建细则  
> 产品交互与选型沿用已定稿决策；§4 起为可直接落地的实现规格。

## 1. 目标交互流程

```
安装：双击 setup.exe → 安装向导（可改安装路径，默认无需管理员）→ 桌面/开始菜单出现图标
启动：双击图标 → 进程静默启动（无黑框、无窗口、任务栏无按钮）
      → 托盘隐藏图标区出现软件图标 + 气泡"正在启动…"
      → 服务就绪后默认浏览器自动打开实际地址（默认 http://127.0.0.1:8001）
二次启动：已实例在跑 → 仅打开浏览器指向已记录端口，然后退出（不弹第二托盘）
退出：托盘图标右键 → 退出（停 uvicorn + 收尾 lifespan，完全退出）
```

关键约束：

- **纯浏览器访问**，不打包浏览器内核（排除 Electron/Tauri）
- 托盘驻留，**不出现在任务栏**（无窗口进程天然满足）
- WSL 收集器逻辑（commit `747d4cf`）不改；打包版仍依赖本机 `wsl.exe` 与配置的发行版名
- 可写数据一律 `%APPDATA%\ai-token-usage\`，安装目录只读

## 2. 技术选型

| 层 | 方案 | 理由 |
|---|---|---|
| 托盘宿主 | pystray + Pillow | 纯 Python，与后端同进程 |
| 打包 | PyInstaller（**onedir** + `console=False`） | 依赖全兼容；启动快、杀软误报低于 onefile |
| 安装器 | Inno Setup | 免费、脚本化、中文向导、自动卸载 |

依赖变更（`pyproject.toml`）：

```toml
dependencies = [
  # ...existing...
  "pystray>=0.19",
  "Pillow>=10.0",
]
[project.optional-dependencies]
dev = [
  # ...existing...
  "pyinstaller>=6.0",
]
```

构建仅支持 **Windows**；Python 版本与开发环境一致（当前 `>=3.11`，建议固定 3.11 或 3.13 其一做发布构建）。

## 3. 架构（进程模型）

单一进程 `ai-token-usage.exe`：

```
主线程：pystray 事件循环（托盘图标、右键菜单、气泡；可短暂阻塞）
服务线程：独立线程内创建 event loop，跑 uvicorn.Server → backend.main:app
启动序列：
  1) 重定向 stdout/stderr/logging → %APPDATA%\ai-token-usage\data\app.log（轮转）
  2) named mutex 单实例；已存在 → 读 instance.json 打开浏览器 → 退出
  3) 解析端口（默认 8001，占用则 +1 找空闲）→ 写 instance.json
  4) 启动 uvicorn 线程 → 轮询 GET /api/config 就绪
  5) 就绪 → webbrowser.open(实际 URL)；托盘 tooltip 就绪
  6) 失败 → 气泡具体原因（端口/依赖/异常），托盘保留“退出/重试”
退出序列：
  server.should_exit = True → 等待服务线程 join(超时 5s)
  → lifespan 内 stop_polling / stop_maintenance / close_db
  → 清理 instance.json → icon.stop() → 释放 mutex
```

### 3.1 目录与路径解析（实现规格）

新增 `backend/paths.py`（唯一路径入口；禁止再写 `Path(__file__).parent.parent.parent`）：

```python
def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))

def app_root() -> Path:
    """安装根 / 仓库根（只读资源）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

def bundle_root() -> Path:
    """PyInstaller 解包资源根（onedir 下通常为 app 根或 _internal）。"""
    return Path(getattr(sys, "_MEIPASS", app_root()))

def data_dir() -> Path:
    """可写数据根。"""
    if is_frozen() and not portable_mode():
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "ai-token-usage" / "data"
    return app_root() / "data"

def config_dir() -> Path:
    """可写配置根（quota_providers.yaml、.env 等）。"""
    if is_frozen() and not portable_mode():
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "ai-token-usage" / "config"
    return app_root() / "config"

def frontend_dist() -> Path:
    for cand in (bundle_root() / "frontend" / "dist", app_root() / "frontend" / "dist"):
        if cand.is_dir():
            return cand
    return bundle_root() / "frontend" / "dist"

def temp_dir() -> Path:
    return Path(os.environ.get("TEMP", tempfile.gettempdir()))

def portable_mode() -> bool:
    return (app_root() / "portable.flag").is_file()

def instance_state_path() -> Path:
    return data_dir() / "instance.json"
```

**路径落点一览（必须与代码一致）：**

| 内容 | 开发版 | 安装版（默认） | Portable（`portable.flag`） |
|------|--------|----------------|---------------------------|
| DB / collector_state / app.log / exchange_rate.json / app_settings.json / maintenance_state.json / backups/ / instance.json | `./data/` | `%APPDATA%\ai-token-usage\data\` | `<exe目录>\data\` |
| `quota_providers.yaml`、可选 `.env` | `./config/` | `%APPDATA%\ai-token-usage\config\` | `<exe目录>\config\` |
| `model_pricing.yaml`（只读种子） | `./config/` | 打包 datas，首启 seed 进 DB | 同左 |
| `frontend/dist` | `./frontend/dist` | 安装目录或 `_internal` | 同左 |
| 采集临时副本（`.hermes-tmp.*`、sqlite copy） | 仓库/TEMP | **`%TEMP%`** | `%TEMP%` |
| 托盘/备份日志轮转 | dev stderr | `app.log` + RotatingFileHandler（1MB × 3） | 同安装版 |

**现有代码必须改到 `paths` 的调用点（阻塞项）：**

| 位置 | 现状 | 改为 |
|------|------|------|
| `backend/config.py` `db_path` / `collector_state_path` / `frontend_dist` | CWD 相对 | `data_dir()/...`、`frontend_dist()` |
| `backend/quota/registry.py:22-23` | `__file__` 三层 parent | `config_dir() / "quota_providers.yaml"` |
| `backend/api/quota.py:29` | 同上 | 与 registry 共用同一 helper |
| `backend/pricing/model_pricing.py:15-16` | 同上 | 种子读 `bundle_root()/config/model_pricing.yaml` 或 `config_dir()` |
| `backend/maintenance.py` `_backup_dir` / 状态文件 | `db_path.parent` | 仍可，但依赖 db_path 已正确 |
| `backend/collectors/*` 临时文件 | 可能落在包目录 | `temp_dir()` |
| `backend/main.py` StaticFiles | `settings.frontend_dist.resolve()` 依赖 CWD | `paths.frontend_dist()` |

首启初始化（`tray_app` 或 `init_user_dirs()`）：

1. 创建 `data_dir()`、`config_dir()`、`backups/`
2. 若 `config_dir()/quota_providers.yaml` 不存在 → 从内置模板复制（占位符，无真实凭据）
3. 不覆盖已有用户配置/DB

### 3.2 实例状态文件 `instance.json`

二次启动、托盘“打开面板”、端口 +1 都依赖它：

```json
{
  "pid": 12345,
  "port": 8001,
  "host": "127.0.0.1",
  "started_at": "2026-09-22T10:00:00Z",
  "base_url": "http://127.0.0.1:8001"
}
```

- 启动时若 mutex 已存在：读该文件，`webbrowser.open(base_url)`，退出码 0
- 文件损坏/不存在：提示“检测到已在运行但无法取得地址”，默认仍试 `http://127.0.0.1:8001`
- 正常退出时删除；崩溃残留由下次启动根据 `pid` 是否存活决定覆盖或复用

### 3.3 环境与设置（安装版如何改端口 / API Key）

优先级：**环境变量 > `config/.env` > 默认值**（与 pydantic-settings 一致，但 `env_file` 指向 `config_dir()/.env`）。

| 变量 | 用途 | 安装版建议 |
|------|------|------------|
| `TOKEN_STAT_PORT` / `TOKEN_STAT_HOST` | 监听 | 默认 8001 / 127.0.0.1 |
| `TOKEN_STAT_API_KEY` | `/api/` 鉴权 | 默认空；**host 非回环时托盘首次启动气泡警告** |
| `TOKEN_STAT_CORS_ORIGINS` | CORS | 同源静态托管时可维持默认 |
| `TOKEN_STAT_WSL_DISTRO` 等 | 采集 | 与开发版相同 |

MVP：安装版通过 APPDATA 下 `.env` 或系统环境变量配置；设置界面改端口/API Key 列为后续迭代（不在本里程碑）。

## 4. 组件明细

### 4.1 `backend/tray_app.py` — 托盘入口（核心新文件，约 250–300 行）

职责拆分（便于单测）：

| 函数 | 职责 |
|------|------|
| `acquire_single_instance() -> bool` | `CreateMutexW`；名建议 `Local\\AiTokenUsageStatistics`（**Inno `AppMutex` 用同一字符串**） |
| `redirect_stdio_and_logging()` | `sys.stdout/stderr` → 日志文件；`logging` 根 logger + RotatingFileHandler |
| `find_free_port(preferred: int) -> int` | bind 探测，失败则 preferred+1…+20 |
| `start_server_thread(host, port)` | 见 §3.4 |
| `wait_ready(base_url, timeout=30s) -> bool` | 轮询 `GET {base_url}/api/config` |
| `write_instance_state` / `clear_instance_state` | §3.2 |
| `show_tray()` | pystray 菜单：打开面板 / 开机自启（可选）/ 退出 |

启动反馈（已定稿，不用百分比气泡）：

1. t=0：托盘图标立刻出现，tooltip「正在启动…」
2. t≈0.5s：一条气泡「AI 用量统计正在启动…」
3. 就绪：`webbrowser.open(base_url)`（就绪信号），tooltip「就绪 · 端口 xxxx」
4. 失败：气泡写明原因（端口占用穷尽 / 启动异常 / 前端资源缺失）

菜单：

- **打开面板**：`webbrowser.open(instance.base_url)`
- **退出**：`server.should_exit = True` → join → 清 state → `icon.stop()`
- （可选）**开机自启**：与 Inno 任务写同一 `HKCU\...\Run` 值

### 3.4 服务线程与 Windows 事件循环（必须按此实现）

```python
def _serve(host: str, port: int) -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    config = uvicorn.Config(
        "backend.main:app",
        host=host,
        port=port,
        log_config=None,          # 已重定向，避免 uvicorn 再挂 stderr
        lifespan="on",
        access_log=False,
    )
    server = uvicorn.Server(config)
    _server_ref.append(server)
    try:
        loop.run_until_complete(server.serve())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
```

- **不要**在主线程跑 uvicorn（会饿死 pystray）
- 退出以 `should_exit` 触发 lifespan 收尾：`stop_polling()` / `stop_maintenance()` / `close_db()`（`main.lifespan` 已具备）
- 服务线程意外结束：托盘 tooltip「服务已停止」+ 气泡一次；菜单仅「退出」
- `wait_ready` 失败：不打开浏览器，走失败气泡

### 4.2 `backend/config.py` — 路径适配

- 引入 `backend.paths`；`Settings` 字段默认值改为 property/`default_factory` 指向 paths
- `model_config` 增加 `env_file = str(config_dir() / ".env")`（frozen 时）
- 开发版行为保持相对仓库根，**现有 pytest 零改动目标**（paths 在非 frozen 时回落 `app_root()/data` 等，并保证可注入 tmp_path）
- 为 paths 写单测（monkeypatch `sys.frozen` / `APPDATA` / `portable.flag`）

### 4.3 图标 — `assets/generate_icon.py`（生成脚本已就绪）

- 采用 **方案 A**（靛蓝→紫渐变 + 白色上升柱）
- 发布前产出 `assets/app.ico`：256/48/32/16 多尺寸（脚本可加 `--ico` 输出）
- 托盘运行时图标：Pillow 从同源 PNG/ICO 加载；16px 托盘区用 16/32 资源，避免缩放糊

### 4.4 `build/tray_app.spec` — PyInstaller 配置

```
entry      = backend/tray_app.py
console    = False
mode       = onedir
name       = ai-token-usage
icon       = assets/app.ico
datas      = frontend/dist → frontend/dist
             config/model_pricing.yaml → config/
             config/quota_providers.example.yaml → config/
hidden     = aiosqlite, uvicorn.logging, uvicorn.loops.auto, uvicorn.protocols.http.auto,
             uvicorn.protocols.websockets.auto, uvicorn.lifespan.on,
             anyio._backends._asyncio, pydantic.deprecated.*  # 以构建警告为准补齐
```

- 静态资源校验：spec/build 脚本若发现 `frontend/dist/index.html` 不存在则 **失败退出**（禁止静默打出无 UI 的包）
- 不打包 `data/`、`.env`、`quota_providers.yaml`（真实凭据）
- onedir 布局：`ai-token-usage/ai-token-usage.exe` + `_internal/`（datas 进 `_internal`）；`frontend_dist()` 按 §3.1 多候选解析
- 构建命令必须在仓库根执行，解释器用发布用 venv

### 4.5 `build/installer.iss` — Inno Setup

| 项 | 值 |
|----|-----|
| `AppId` | 固定 GUID（一次生成，终身不变） |
| `AppName` | AI 用量统计 |
| `AppVersion` | 与 `pyproject.toml` 同步（build 脚本写入 `.iss` 或 `/DAppVersion=`） |
| `OutputBaseFilename` | `AI-Token-Usage-Setup-{version}`（**ASCII 文件名**，避免工具链编码问题；向导内显示中文名） |
| `PrivilegesRequired` | `dynamic`；默认 per-user `%LOCALAPPDATA%\Programs\ai-token-usage` |
| `AppMutex` | `AiTokenUsageStatistics`（与 `CreateMutexW` 名一致；注意 Inno 不带 `Local\` 前缀时的匹配行为，构建时验证一次） |
| 快捷方式 | 桌面 + 开始菜单 |
| 任务 | 「开机自启」默认不勾 → `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` |
| 完成页 | 「立即运行」默认勾选 |
| 卸载 | 默认**保留**用户数据；提供任务/代码勾选「同时删除用户数据」→ 删 `%APPDATA%\ai-token-usage` |
| 覆盖升级 | 不删 APPDATA；正在运行时用 AppMutex 提示先退出 |

### 4.6 `build/build_exe.py` — 一键构建

```
1) 读 pyproject 版本号
2) npm run build（frontend）
3) 校验 frontend/dist/index.html
4) pyinstaller build/tray_app.spec --noconfirm
5) iscc /DAppVersion=... build/installer.iss
6) 产物：build/output/AI-Token-Usage-Setup-{version}.exe
   绿色版：build/dist/ai-token-usage/ 目录（可 zip）
```

失败即非零退出；不在脚本里 `pip install` 运行时依赖以外的猜测性补丁。

## 5. 已定稿决策记录

| 决策点 | 结论 |
|---|---|
| exe 流程 | setup.exe 安装后点图标启动；onedir 目录可作绿色版 |
| 绿色版数据目录 | 若 exe 旁存在 `portable.flag` → 数据/配置放 exe 旁 `data/`、`config/`；否则安装版走 APPDATA |
| 启动等待提示 | 一条「正在启动」气泡 + 就绪后打开浏览器；**否决百分比气泡** |
| 数据/配置目录 | 见 §3.1 表；升级覆盖保留；卸载默认保留 |
| 从开发版迁移 | 手工复制 `data/token_statistic.db` → APPDATA `data/`；**不自动迁移** |
| 凭据迁移 | **不迁移**，设置界面/`config/quota_providers.yaml` 重填 |
| 开机自启 | 默认关；安装任务可勾选；托盘可切换 |
| 退出语义 | 完全退出，不留服务 |
| 签名 | 暂不买证书；接受 SmartScreen「更多信息→仍要运行」 |
| 监听 | 默认仅 127.0.0.1；若 host 为 0.0.0.0 且未设 API Key → 启动气泡警告 |
| 计费种子 | 首启/升级将包内 `model_pricing.yaml` 中**缺失模型**插入 DB；不覆盖已有自定义价 |
| 无 WSL | 服务照常启动，采集为空；托盘 tooltip 可显示「WSL 不可用」（读 `is_wsl_running()`） |

## 6. 实施步骤 checklist

1. [ ] `backend/paths.py` + 单测（frozen / portable / APPDATA）
2. [ ] `backend/config.py`、`quota/registry.py`、`api/quota.py`、`pricing/model_pricing.py`、`main.py` 切到 paths
3. [ ] 采集临时文件改 `%TEMP%`
4. [ ] `backend/tray_app.py`（mutex / 日志轮转 / 端口 / uvicorn 线程 / 气泡 / 菜单 / instance.json）
5. [ ] 图标定稿（方案 A）→ `assets/app.ico` 多尺寸
6. [ ] `build/tray_app.spec` + 构建补齐 hidden imports（以缺失告警为准）
7. [ ] `build/installer.iss`（AppMutex / 版本 / 自启任务 / 卸载删数据勾选）
8. [ ] `build/build_exe.py` 一键串联 + 版本注入
9. [ ] `pyproject.toml` 补 pystray、Pillow、pyinstaller
10. [ ] 端到端验收（见 §7）
11. [ ] README「桌面版」小节：安装、数据目录、无 WSL 说明、SmartScreen

## 7. 验收清单（端到端）

| # | 场景 | 期望 |
|---|------|------|
| 1 | 干净安装到默认 per-user 路径 | 无管理员；桌面/开始菜单有图标 |
| 2 | 首次启动 | 托盘 + 一条启动气泡 + 浏览器打开 UI；`%APPDATA%\ai-token-usage\data\` 出现 DB |
| 3 | 二次启动 | 不出现第二托盘；浏览器打开**实际**端口 |
| 4 | 8001 被占用 | 自动 8002…；气泡与 instance.json 为实际端口 |
| 5 | 托盘→退出 | 进程消失；instance.json 删除；DB 可再打开 |
| 6 | 覆盖升级（旧版运行中） | Inno 提示先退出；升级后 DB/配置保留 |
| 7 | 卸载默认 | 程序删掉，APPDATA 数据仍在 |
| 8 | 卸载勾选删数据 | `%APPDATA%\ai-token-usage` 删除 |
| 9 | 无 WSL / 发行版未运行 | UI 可开，用量为零或增量停滞，无崩溃 |
| 10 | 设置 API Key 后浏览器刷新 | 无 Key 时 API 401（UI 需带 Key 或仅本机） |
| 11 | portable.flag 绿色版 | 数据在 exe 旁 `data/`，卸载器无关 |
| 12 | 覆盖安装后新模型计费 | 缺失模型被 seed，自定义价不被重置 |

## 8. 风险与已知摩擦

| 风险 | 缓解 |
|------|------|
| 未签名 exe：SmartScreen / 杀软误报 | onedir；说明文档写清绕过步骤；观察后再定买证书 |
| PyInstaller 缺 hook（pydantic/uvicorn/aiosqlite） | spec 预置常见 hidden；以构建运行时 ImportError 补齐；CI 可做“打包冒烟” |
| pystray 气泡在个别环境不弹 | 降级：tooltip 状态 + 就绪打开浏览器（主线反馈不变） |
| Windows 事件循环与托盘混用 | 强制 Selector 策略 + 独立线程（§3.4） |
| 中文安装包名 | 输出 ASCII 文件名，显示名用中文 |
| 用户把 host 改成 0.0.0.0 | 启动气泡警告 + README 要求设 API Key |
| 工作目录导致静态资源 404 | 全部走 `paths.frontend_dist()`，不依赖 CWD |
| 程序装到 Program Files 可写失败 | 可写路径已隔离到 APPDATA/TEMP；spec 不打包可写数据 |

## 9. 后续迭代（本里程碑不做）

- 设置界面改端口 / API Key / 自启（现用 `.env` + 安装任务）
- 代码签名与自动更新（Squirrel/自写 updater）
- 开箱即用的「一键从开发版迁移数据」
- 多语言安装向导
- 托盘菜单里的「打开数据目录」「查看日志」
