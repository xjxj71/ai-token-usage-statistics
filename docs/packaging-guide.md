# Windows 桌面版打包教程

> 产出物：`build/output/AI-Token-Usage-Setup-0.1.2.exe`  
> 本文记录本机完整可复现步骤（工具安装在 **F 盘**，不写 C 盘）。  
> **0.1.1** 修复 `_ssl.pyd` / OpenSSL 入口错误；**0.1.2** 修复采集器 `wsl.exe` 反复弹出控制台黑框。

## 0. 产物说明

| 文件 | 说明 |
|------|------|
| `build/output/AI-Token-Usage-Setup-<ver>.exe` | 安装包（Inno Setup） |
| `dist/ai-token-usage/` | PyInstaller onedir 绿色目录（可直接拷走） |
| `assets/app.ico` / `assets/tray-32.png` | 生成的图标资源（不入库） |
| `build/pyi_rth_ssl_fix.py` | 运行时预加载 conda OpenSSL，防止 `_ssl.pyd` 入口错误 |

安装后：

- 默认安装到 `%LOCALAPPDATA%\Programs\ai-token-usage`（可改路径）
- 用户数据在 `%APPDATA%\ai-token-usage\{data,config}`
- 双击图标 → 托盘驻留 → 浏览器打开 `http://127.0.0.1:8001`（端口被占会自动 +1）
- 托盘右键「退出」完全退出
- 未签名：SmartScreen 首次「更多信息 → 仍要运行」

## 1. 环境要求

| 工具 | 本机位置 | 用途 |
|------|----------|------|
| Node.js / npm | `F:\nvm\nodejs\` | 前端构建 |
| Python 3.11+（venv） | 项目 `.venv-win\` | 运行与 PyInstaller |
| Inno Setup 6.7.3 | `F:\Tools\InnoSetup\` | 生成 setup.exe |
| Inno 安装包缓存 | `F:\Tools\Installers\innosetup-6.7.3.exe` | 重装用 |

### 安装 Inno Setup 到 F 盘（已做）

```powershell
# 下载
Invoke-WebRequest -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' `
  -OutFile 'F:\Tools\Installers\innosetup-6.7.3.exe'

# 静默安装到 F 盘
Start-Process 'F:\Tools\Installers\innosetup-6.7.3.exe' -ArgumentList `
  '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/DIR=F:\Tools\InnoSetup','/COMPONENTS=' -Wait
```

验证：`F:\Tools\InnoSetup\ISCC.exe` 存在即可。

### Python 依赖

```powershell
cd "D:\research project\ai-token-usage-statistics"
.venv-win\Scripts\python.exe -m pip install -e ".[dev]"
# 含 pystray / pillow / pyinstaller
```

## 2. 一键打包（推荐）

```powershell
cd "D:\research project\ai-token-usage-statistics"

# 若 ISCC 不在 PATH，先加入或直接用绝对路径
$env:PATH = "F:\Tools\InnoSetup;$env:PATH"

.venv-win\Scripts\python.exe build\build_exe.py
```

`build/build_exe.py` 顺序执行：

1. `npm run build`（frontend）
2. `assets/generate_icon.py --export-build-assets` → `app.ico` + `tray-32.png`
3. `pyinstaller build/tray_app.spec` → `dist/ai-token-usage/`
4. `ISCC.exe /DAppVersion=<ver> build/installer.iss` → `build/output/AI-Token-Usage-Setup-<ver>.exe`

版本号读取自 `pyproject.toml` 的 `version`。

## 3. 分步打包（排障用）

```powershell
cd "D:\research project\ai-token-usage-statistics"

# 3.1 前端（约 1–2 分钟）
& F:\nvm\nodejs\npm.cmd run build
# 必须存在 frontend/dist/index.html

# 3.2 图标
.venv-win\Scripts\python.exe assets\generate_icon.py --export-build-assets

# 3.3 PyInstaller onedir（conda/venv 混用时很慢，约 10–20 分钟）
# 建议写入 bat 后台跑，避免终端超时杀进程：
#   .venv-win\Scripts\python.exe -m PyInstaller --noconfirm build\tray_app.spec
# 成功标志：dist\ai-token-usage\ai-token-usage.exe
# 日志可重定向到 F:\Tools\BuildLogs\pyi-full.log

# 3.4 安装器（版本号必须显式传入，installer.iss 缺参会直接报错；
#     build_exe.py 会自动从 pyproject.toml 读取并传入）
New-Item -ItemType Directory -Force build\output | Out-Null
& F:\Tools\InnoSetup\ISCC.exe /DAppVersion=0.1.2 build\installer.iss
# 输出：build\output\AI-Token-Usage-Setup-0.1.2.exe
```

## 4. 关键脚本与路径约定

| 文件 | 职责 |
|------|------|
| `backend/paths.py` | 开发 / 安装 / portable 三套路径 |
| `backend/tray_app.py` | 托盘入口、单实例 mutex、uvicorn 线程 |
| `build/tray_app.spec` | PyInstaller onedir + datas/hidden |
| `build/installer.iss` | Inno：per-user、快捷方式、自启任务、卸载删数据 |
| `build/build_exe.py` | 串联 1–4 |

**路径约定（frozen）：**

- 可写数据：`%APPDATA%\ai-token-usage\`
- 绿色版：exe 旁放 `portable.flag`，数据改到 `<exe>\data` / `<exe>\config`
- 采集临时文件：`%TEMP%`
- 静态前端：打包 datas → `_internal/frontend/dist`（`paths.frontend_dist()` 多候选解析）

**PyInstaller 输出目录：** 默认 `dist/`（仓库根），**不是** `build/dist/`。`installer.iss` 已指向 `..\dist\ai-token-usage\*`。

## 5. 安装器任务选项

安装向导 Tasks（英文界面，无官方简中 .isl）：

- Create desktop shortcut
- Start with Windows（写 HKCU Run，注册命令带 `--minimized`：开机自启不弹浏览器面板，托盘正常驻留）
- Delete user data when uninstalling（默认不勾；勾选后卸载删 `%APPDATA%\ai-token-usage`）

## 6. 验收清单（手工）

1. 干净安装 → 桌面图标出现  
2. 首次启动 → 托盘 + 浏览器打开面板  
3. 二次启动 → 不出现第二托盘，浏览器仍可打开  
4. 托盘退出 → 进程消失  
5. 覆盖升级 → `%APPDATA%` 数据保留  
6. 卸载默认 → 数据仍在；勾选删数据 → 数据删除  

## 7. 常见问题

| 现象 | 处理 |
|------|------|
| SmartScreen 拦截 | 更多信息 → 仍要运行（未买代码签名证书） |
| PyInstaller 极慢 | 本机 venv 挂在 conda Python 上会反复探测；耐心等待或改用独立 python.org 解释器重建 venv |
| 启动无界面 | 看 `%APPDATA%\ai-token-usage\data\app.log` |
| 端口被占 | 自动 8002…；地址写在 `%APPDATA%\ai-token-usage\data\instance.json` |
| ISCC 报 PrivilegesRequired | 脚本使用 `lowest` + `PrivilegesRequiredOverridesAllowed=dialog`（兼容 Inno 6） |
| 前端 404 | 确认打包前执行过 `npm run build` 且 `frontend/dist/index.html` 存在 |
| 启动报 `COMP_get_type` / `_ssl.pyd` 入口找不到 | 已修（0.1.1）：强制打入 conda OpenSSL + 预加载钩子 |
| 运行中反复闪黑色控制台 | 已修（0.1.2）：`wsl.exe` 子进程加 `CREATE_NO_WINDOW`。请用 0.1.2+ |

## 8. 重新发布检查单

1. 改 `pyproject.toml` 的 `version`
2. `python build\build_exe.py`
3. 在干净虚拟机/另一用户安装验收
4. 归档 `build/output/AI-Token-Usage-Setup-<ver>.exe`（可附 SHA256）
