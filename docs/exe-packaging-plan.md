# Windows 桌面化（exe 安装包）实施方案

> 状态：**方案已评审定稿，待实现**（本文档即实施依据）
> 日期：2026-09-19
> 前置讨论结论已全部并入本文；实现时按"组件明细"逐项落地即可。

## 1. 目标交互流程

```
安装：双击 setup.exe → 安装向导（可改安装路径，无需管理员）→ 桌面/开始菜单出现图标
启动：双击图标 → 进程静默启动（无黑框、无窗口、任务栏无按钮）
      → 托盘隐藏图标区出现软件图标 + 气泡"正在启动…"
      → 服务就绪后默认浏览器自动打开 http://127.0.0.1:8001
退出：托盘图标右键 → 退出（同时停掉 uvicorn，完全退出）
```

关键约束：

- **纯浏览器访问**，不打包浏览器内核（排除 Electron/Tauri）
- 托盘驻留，**不出现在任务栏**（无窗口进程天然满足）
- WSL 收集器守卫（commit `747d4cf`）在打包版正常工作，无需改动

## 2. 技术选型

| 层 | 方案 | 理由 |
|---|---|---|
| 托盘宿主 | pystray + Pillow | 纯 Python，与后端同进程 |
| 打包 | PyInstaller（**onedir** + noconsole） | 现有依赖全兼容；onedir 比 onefile 启动快、杀软误报低 |
| 安装器 | Inno Setup | 免费、脚本化、中文向导、自动卸载程序 |

新增运行时依赖：`pystray`、`Pillow`；新增构建依赖：`pyinstaller`（dev 组）。

## 3. 架构（进程模型）

单一进程 `ai-token-usage.exe`：

```
主线程：pystray 事件循环（托盘图标、右键菜单、气泡通知）
后台线程：uvicorn.Server(config) 直跑 backend.main:app（127.0.0.1，默认 8001）
启动序列：named-mutex 单实例检查 → 启动 uvicorn 线程 → 轮询端口/健康检查
        → 就绪后 webbrowser.open() → 托盘 tooltip 恢复正常
```

## 4. 组件明细

### 4.1 `backend/tray_app.py` — 托盘入口（核心新文件，约 200 行）

- **单实例**：Windows named mutex（`CreateMutexW`，ctypes）。二次启动时直接
  `webbrowser.open()` 聚焦已有实例然后退出；**同一个 mutex 名复用给 Inno 的
  `AppMutex`**，安装器/卸载器据此检测"软件正在运行"并提示先退出
- **noconsole 关键处理**：`--noconsole` 下 `sys.stdout/stderr` 为 `None`，
  uvicorn 默认往 stderr 打日志会崩——入口最先把日志重定向到
  `%APPDATA%\ai-token-usage\data\app.log`
- **启动反馈（已定稿，不用百分比气泡）**：
  1. t=0：托盘图标立刻出现，tooltip"正在启动…"，图标用启动中样式
  2. t≈0.5s：一条气泡通知"AI 用量统计正在启动…"
  3. 就绪：浏览器自动打开（最强就绪信号），不再弹第二条气泡
  4. 失败：气泡给出具体原因（端口占用/启动异常）
- **托盘菜单**：打开面板 / 退出（`server.should_exit = True` + `icon.stop()`，优雅关闭）
- **端口占用**：8001 被占时自动 +1 找空闲端口，气泡告知实际地址

### 4.2 `backend/config.py` — 冻结环境路径适配（约 15 行）

`getattr(sys, "frozen", False)` 为真时：

| 内容 | 位置 |
|---|---|
| 数据/状态（db、collector_state、app.log） | `%APPDATA%\ai-token-usage\data\` |
| 用户配置（quota_providers.yaml 等） | `%APPDATA%\ai-token-usage\config\`（首启从内置默认复制） |
| 前端静态资源 frontend/dist | 安装目录（只读） |

开发版（仓库运行）路径行为不变，测试零影响。

**设计要点**：数据放 APPDATA 而非安装目录——安装到 Program Files 也可写；
升级覆盖安装天然保留数据；卸载默认不碰（提供"同时删除用户数据"勾选）。

### 4.3 图标 — `assets/generate_icon.py`（✅ 已完成）

1024px 超采样渲染，产出三候选（`assets/icon-previews/`）：

- **A（推荐）**：靛蓝→紫渐变底 + 白色上升柱，**16px 下不失真**（视觉模型评审结论）
- B（否决）：折线+箭头，16px 糊成斜杠，箭头比例失衡
- C（备选）：深底四色柱，辨识度高但深色托盘区易融底；采用需加强边框/加粗柱条

正式构建时用选定变体生成多尺寸 `assets/app.ico`（256/48/32/16）。

### 4.4 `build/tray_app.spec` — PyInstaller 配置

- 入口 `backend/tray_app.py`，`console=False`，onedir
- datas：`frontend/dist`（构建前 `npm run build`）+ `config/` 默认配置 + 计费表
- hidden imports：aiosqlite、uvicorn 内部模块（构建时以 `pyi-makespec` 试错补齐；
  pydantic v2 有官方 hook）
- 图标：`assets/app.ico`

### 4.5 `build/installer.iss` — Inno Setup 脚本

- `PrivilegesRequired=dynamic`：默认 per-user
  （`%LOCALAPPDATA%\Programs\ai-token-usage`），**向导可浏览改路径**；选受保护
  目录（Program Files）时自动请求管理员
- `AppMutex` = 单实例 mutex 名 → 升级/卸载检测运行中并提示
- 桌面 + 开始菜单快捷方式；完成页"立即运行"勾选
- 可选"开机自启"勾选（写 `HKCU\...\Run`，默认不勾，托盘菜单可切换）
- 卸载器；覆盖升级保留 APPDATA 数据

### 4.6 `build/build_exe.py` — 一键构建

`npm run build → pyinstaller（spec）→ iscc（iss）`，产出
`build/output/AI用量统计-setup.exe`。

## 5. 已定稿决策记录

| 决策点 | 结论 |
|---|---|
| exe 流程 | setup.exe 先安装（向导可改路径），装完点图标启动；PyInstaller 产物可直接当绿色版 |
| 启动等待提示 | 一条"正在启动"气泡 + 就绪后浏览器自动打开；**否决百分比气泡**（2~4s 无真实进度、Windows 通知不能原地更新、连发多条吵） |
| 数据/配置目录 | 打包版固定 `%APPDATA%\ai-token-usage\`（可写性/升级保留/卸载默认保留） |
| 从开发版迁移 | 手工复制 `data/token_statistic.db` 到 `%APPDATA%\ai-token-usage\data\`，一次性 |
| 凭据迁移 | **不迁移**——智谱 key/小米 cookie 由用户在设置界面重新填写（与"凭据仅用户手填"原则一致） |
| 开机自启 | 默认关；安装向导可勾选；托盘菜单可切换 |
| 退出语义 | 退出即完全退出，不留后台服务 |
| 签名 | 暂不购买证书；SmartScreen 首次警告（"更多信息→仍要运行"）为已知摩擦 |

## 6. 实施步骤 checklist

1. [ ] `backend/tray_app.py`（单实例/日志重定向/uvicorn 线程/气泡/菜单）
2. [ ] `backend/config.py` frozen 路径适配 + 单测
3. [ ] 图标定稿 → 生成 `assets/app.ico`（推荐方案 A，待最终确认）
4. [ ] `build/tray_app.spec` + 打包试错补 hidden imports
5. [ ] `build/installer.iss`（AppMutex/路径向导/快捷方式/自启勾选）
6. [ ] `build/build_exe.py` 一键串联
7. [ ] 端到端验证：安装→图标启动→托盘+浏览器→右键退出→覆盖升级→卸载
8. [ ] `pyproject.toml` 补依赖（pystray、Pillow；dev 加 pyinstaller）

## 7. 风险与已知摩擦

- **未签名 exe**：SmartScreen 警告 + 杀软偶发误报（onedir 已大幅缓解），观察后再定是否买证书
- **pydantic/uvicorn PyInstaller hooks**：以官方 hook 为主，缺失模块在打包试错时补
- **气泡通知兼容性**：pystray 的 notify 在 Win10/11 走 toast；若个别环境不弹，
  降级方案为 tooltip 状态变化 + 浏览器自动打开（反馈主线不受影响）
