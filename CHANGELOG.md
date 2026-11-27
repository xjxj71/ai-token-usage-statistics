# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **多主题切换**：经典深色 / 曜石 Obsidian / 晨雾 Daylight / 暖砂 Warm Sand / 霓虹 Neon 五套主题，头部调色板按钮切换，选择持久化到 localStorage 并在首帧前应用（无闪烁）。全部颜色收敛为 `app.css` CSS 变量（`[data-theme=...]` 覆盖），ECharts 通过 `theme.svelte.ts` 从同一组变量取运行时调色板，主题切换时图表自动重绘；Agent 身份色、表格徽章、筛选圆点跨主题保持一致（徽章文字色按主题文字色自动混合保证对比度）。设计原型见 `design/prototypes/`
- **套餐倍率自动同步**：模型消耗倍率（抵扣系数/消耗倍率）不再硬编码，改为定时从官方文档中心抓取解析（`backend/quota/multipliers.py`：启动即拉取 + 每 6h 刷新 + `POST /api/quota/multipliers/refresh` 手动刷新，`data/model_multipliers.json` 持久化缓存，失败自动回退内置快照，卡片标注数据更新时间）
  - 解析前先规范化官方改价用的编辑标记（`~~旧值~~ 新值` 删除线、`<del>`、加粗、脚注），取当前生效值；官方标注的限时活动（如 GLM-5.3-Flash 11-24 至 12-24 半价）在角标上显示「限时」并在说明里给出区间
  - 若某次解析比上次少了模型，更新照常生效（官方下线/改名需如实反映），同时写 WARNING 日志便于发现页面格式变化
  - 智谱：解析 `docs.bigmodel.cn/cn/coding-plan/overview.md`（积分抵扣系数 + 积分额度），历史 V2 prompt 制倍率取自套餐改版公告 `usage-revision.md`；`docs.z.ai` 同构英文页作备用源。用量接口返回 `CREDIT_LIMIT` / `TOKENS_LIMIT` 时自动识别套餐制式并匹配对应倍率与额度表
  - 小米：解析 `mimo.mi.com` Token Plan 订阅文档（语言模型 Credits 折算表 + 夜间 0.8x + 月度额度）
  - 卡片展示随官方数据变化：智谱 GLM-5.4 / GLM-5.3 / GLM-5.3-Flash（输入/缓存/输出抵扣系数，非高峰 5 折，高峰周一至五 14-18）、小米 mimo-v2.6-pro / flash / pro-ultraspeed（Credits/Token，夜间 00-08 0.8x）
- 智谱本地估算按套餐制式区分：积分制按 Token × 抵扣系数 ÷ 10000 折算积分（新积分制额度 2000/12000/28000 credits），历史 V2 prompt 制保留调用次数估算；`quota_providers.yaml` 新增 `plan_mode`（auto/credits/prompts）供手动覆盖
- **Qoder 采集器（国际版）**：监控 Qoder 桌面客户端（国际版）的 Token 用量。读取 `~/.qoder/` 下两类本地文件，零侵入、无需配置
  - 运行日志 `logs/runs/*/qodercli.log`：`[permission-check]` 权限检查的上下文转储中 assistant 消息携带每次模型请求的 `message.usage`，按消息 uuid 去重（同一响应会被后续工具调用反复转储）
  - 会话转录 `projects/**/*.jsonl`：压缩（compact）事件的 `compactUsage`（compaction 也是真实计费请求）；转录同时提供 会话→工作目录 映射，用于项目归属
  - token 口径转换：Qoder 的 `input_tokens` 为含缓存的提示词总量（OpenAI 口径），入库时拆为「未缓存输入 + 缓存读取 + 缓存写入」
  - 已知盲区（有意不计）：转录落盘时剥离 `message.usage`；`turn.finished` 事件 token 字段当前恒为 0，且语义上是逐请求记录的聚合，计入会重复计数
  - 前端 FilterBar / 会话明细 / 使用记录新增 qoder 标签色（天蓝）
- **Codex 采集器**：监控 OpenAI Codex CLI 的 Token 用量。读取 `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` 中的 `token_usage_record` 事件（旧版 CLI 兜底解析 `token_count`），零侵入、无需配置
  - token 口径转换：Codex 的 `input_tokens` 含缓存命中，入库时拆为「未缓存输入 + 缓存读取」；`reasoning_output_tokens` 计入思考 Token
  - 按文件字节偏移水位增量读取；session_id / cwd / 模型上下文按文件缓存，续读时仍可正确归属项目与模型
  - 前端 FilterBar / 会话明细 / 使用记录新增 codex 标签色（石板灰）
  - 定价 YAML 新增 gpt-5 / gpt-5-mini / gpt-5-nano / gpt-5-pro / gpt-5.1 系列 / gpt-5-codex / gpt-5.1-codex(-max) / codex-mini-latest 条目
- **项目维度分析**：新增 `token_usage.project` 列（取会话工作目录最后一段），`/api/summary?group_by=project` 聚合 + 前端"项目消耗分布"条形图 + FilterBar 项目多选筛选 + `/api/projects` 端点（数据来自 claude-code / openclaude / zcode / codex）
- **思考 Token 统计**：新增 `token_usage.reasoning_tokens` 列（zcode / opencode / mimocode / codex 采集），第 8 张统计卡、使用记录"思考"列、CSV 导出、会话与摘要中的思考 Token 汇总
- **会话明细钻取**：新增 `GET /api/sessions`（按 Agent×会话聚合，含项目/模型/Token/费用）与 `/api/usage?session_id=` 过滤；前端"会话明细"表点击行内展开查看该会话每条请求
- **环比对比**：`range_utils.previous_window()` 计算等长上一周期；`/api/summary?compare=true` 返回 `previous` 总量；统计卡显示"较上期"涨跌角标（费用卡下降=绿色）
- **汇率自动获取**：新增 `backend/exchange_rate.py`（open.er-api.com，12h 缓存 + `data/exchange_rate.json` 持久化 + 静态值回退）；`/api/config` 返回生效汇率与来源，`POST /api/config/exchange-rate/refresh` 强制刷新；页眉展示汇率 + 刷新按钮
- **用量报告**：新增 `GET /api/report`（消耗概览 + 环比 + Top Agent/模型/项目 + 套餐余量 + Markdown 文本）；前端 ReportCard 折叠面板，支持一键复制
- **数据保留与备份**：新增 `backend/maintenance.py` 与 `usage_daily` 归档表
  - 保留策略：超期明细先按 天×Agent×模型×项目 聚合进 `usage_daily` 再删除；summary/trend/cache-ratio/distinct 查询自动 UNION 归档数据，历史趋势与汇总不丢失
  - 备份：SQLite 在线备份到 `data/backups/`（每日自动 + 手动），保留最新 N 个，支持列表/下载/删除
  - 新端点：`GET/PUT /api/config/data`、`POST /api/maintenance/cleanup`、`POST /api/backup`、`GET /api/backups`、`GET/DELETE /api/backups/{name}`
  - 前端"数据管理"面板：保留天数/备份策略设置、立即清理、立即备份、备份列表
  - 环境变量：`TOKEN_STAT_RETENTION_DAYS` / `TOKEN_STAT_BACKUP_KEEP` / `TOKEN_STAT_AUTO_BACKUP`
- **数据库迁移机制**：`init_db` 内置 `PRAGMA user_version` 迁移——自动补列（project / reasoning_tokens）、建 `usage_daily` 与会话索引，并为历史记录从 `raw_data` 一次性回填
- 共享守卫提取到 `backend/api/deps.py`（`require_local_or_key`），quota 配置、汇率刷新、备份/清理接口共用
- ZCode 采集器：监控 ZCode CLI 的 Token 用量。读取 `~/.zcode/cli/db/db.sqlite` 的 `model_usage` 表（每次模型请求一行），零侵入、无需配置
  - WAL 快照读取：复制主库 + WAL 副本后查询，不干扰正在写入的 ZCode 进程
  - 以 `completed_at` 为水位，进行中的请求在完成后自动补收；子代理（Explore 等）与后台请求计入 `zcode` 名下
  - 新增 `glm-5.3` 定价条目（估算值，可在前端定价表中调整）
- 新增共享工具 `sqlite_utils.copy_sqlite_with_wal()`（从 Hermes 采集器提取）

### Changed
- 前端图表库 echarts 5.6.0 → 6.1.0（修复中危 XSS 公告 GHSA-fgmj-fm8m-jvvx）。仅改动本项目的 `frontend/package.json` 与 lock 文件（连带其渲染引擎 zrender），未做全局安装。官方列出的三处不兼容（默认主题、坐标轴标签默认防溢出、富文本样式继承）均不涉及本项目用法——六个图表都显式使用内置 `dark` 主题且未用富文本

### Security
- 凭据配置 `config/quota_providers.yaml` 移出 git 跟踪，提供 `quota_providers.example.yaml` 模板
- `PUT /api/quota/config` 仅允许本机调用（或携带有效 `X-API-Key`），响应不再回显 session token
- CORS 默认来源收紧为本地开发服务器

### Fixed
- 修复 zcode 的费用、总 Token 与缓存命中率失真：zcode 采集器直接沿用了 ZCode 源库的 `input_tokens`，而那是**含缓存读取**的完整提示词长度（供应商原始返回 `totalTokens = inputTokens + outputTokens`），入库前未换算，费用把缓存部分又按全价算了一遍。现与其余采集器统一为「未命中输入」口径。真实数据（近 30 天）：输入 13.2 亿 → 3556 万，费用 $844.61 → $342.39（token 口径修正后按官方价），缓存命中率由显示的 49% 回到 97.8%
- 修复 Hermes（WSL / Windows）用量与费用虚高：旧采集器对进行中的会话每小时写一行**累计值**，而统计是按行求和的，一个会话开着几小时就被重复计入几次。真实数据（近 30 天）：输入 3330 万 → 924 万，费用 $259.28 → $17.48。现改为「每小时写增量、会话结束时合并成一行总量」，仍保持写入绝对值的幂等性——状态文件损坏后重写也是同一个数，不会重复计数
- 修复定价导致费用为 0 或与定价表对不上：
  - 入库计费原先只读 YAML，而定价表（前端可编辑、可从 OpenRouter 刷新）只用于展示，改了价格不生效。现定价表就是运行时计价的依据
  - 模型首次出现而当时没有价格时，定价表会被自动插入一行全 0 的占位行，之后永远停在 0 价。现全 0 行视为占位，YAML 有价即自动跟进（用户设过的非 0 价格不动）
  - GLM、MiMo 条目原为「TBD 估算值」且偏差很大（glm-5.3 估算 $0.5/$2.0，官方 $1.4/$4.4；mimo-v2.6-pro 缓存价估算 $0.2，官方 $0.0036）。现换成 z.ai / mimo.mi.com 官方美元价，并补齐 glm-5.4、glm-5.3-Flash(X)、glm-5.2、glm-4.6/4.7、mimo-v2.6-flash / pro-ultraspeed 及 MiMo Code 的「供应商/模型」写法。glm-5.4 官方尚未公布标准 API 价格，暂按 GLM-5.3 官方价代估
- 以上三项配套一次性数据迁移（`user_version` 1 → 2，`backend/db/data_migrations.py`）：启动时自动把历史行归一到新口径、升级未被改动的默认价、补算此前为 0 的费用，**只重算能证明是按价目表算出来的费用**（hanako / openclaw / Hermes 记录的供应商实际花费原样保留）。迁移前在 `data/backups/` 留一份 `*_pre-v2.db` 副本，升级后统计数字会变化属预期
- 套餐余量本地估算改为直接按行求和：历史数据与采集器统一口径后不再需要特判（此前按采集器分别处理的逻辑已随之移除）
- 修复套餐卡片模型倍率过期：原展示的 glm-5.2 / glm-5-turbo / glm-4.7 与 mimo-v2.5 系列均已被官方套餐下线（mimo-v2.5 系列 2026-10-21 下线），倍率数值也不再适用；现展示当前官方模型与倍率并自动保持最新
- 修复官方文档调价标记导致模型被静默丢弃：官网给 GLM-5.3-Flash 挂限时半价时用「~~旧值~~ 新值」标记、名称单元格内加反斜杠换行，原解析器不识别，实测积分制/历史 V2 两套倍率表都丢了整个 Flash 模型（并连带让本地估算对其套用别的模型系数）
- 修复解析出的高峰/夜间时段只写进说明文字、未回写模型字段的问题（历史 V2 套餐角标直接渲染该字段，官方调整时段后会与说明不一致）
- 修复 OpenClaude 采集器被误改为 `openclaw` 导致的采集中断与数据混淆
- custom 时间范围 `to` 日期整天纳入统计；非法 range 返回 400 而非静默回退
- SSE 改为每客户端队列，消除多客户端通知丢失
- 采集器状态文件损坏时自动重置而非每轮崩溃
- 采集循环中的阻塞 IO（wsl.exe、UNC 复制、JSONL 扫描、SQLite、YAML）全部移入线程池
- 筛选栏 agent/模型列表改为随 SSE 实时刷新——页面打开期间新出现的 agent 自动进入筛选栏，无需手动刷新页面
- 修复新模型自动入库时一律以 0 价插入、挡住 YAML 已配置定价的问题（`glm-5.3` 费用显示为 0 的根因）；已有 0 价行可通过定价表或 API 修正
- 修复套餐卡片模型消耗倍数展示不全：旧条件 `off_peak < 1` 导致智谱 glm-5.2 / glm-5-turbo 的「夜间 2x」加成倍数被隐藏；现在高峰/夜间倍数完整展示、标注生效时段（智谱 高峰 14-18、小米 夜间 00-08），1x 模型（glm-4.7）也以「1x」角标显示
- 修复 qoder 记录已入库但筛选栏不显示 qoder 选项：`/api/agents` 的 `SUPPORTED_AGENTS` 白名单漏加 qoder；新增回归测试保证已注册采集器必然在白名单内

## [0.4.0] - 2026-07-08

### Added
- **套餐余量监控**：新增 `backend/quota/` 模块，支持查询大模型套餐剩余用量
  - **智谱 GLM Coding Plan**：通过 `open.bigmodel.cn/api/biz/user/subscription/*` 接口查询 5 小时窗口 + 周额度
  - **小米 MiMo Token Plan**：通过 `platform.xiaomimimo.com/api/v1/tokenPlan/*` 接口查询 Credits 用量
  - Provider 模式架构，后续扩展新 Provider 只需实现 `QuotaProvider` 基类
  - 无凭证时自动回退到本地估算（从 `token_usage` 表按模型聚合反推消耗）
- **前端 PlanQuotaCard 组件**：顶部卡片区域展示套餐等级、进度条、到期时间、模型消耗系数
  - 可折叠设置面板，支持在线配置启用/停用、切换套餐等级、填写 Session Token
- **新增 API 端点**：`GET /api/quota`、`POST /api/quota/refresh`、`GET /api/quota/providers`、`PUT /api/quota/config`
- **新增测试**：`tests/test_quota.py`（13 个单元/集成测试）
- **配置文件**：`config/quota_providers.yaml`（含 Cookie 获取说明注释）

### Notes
- 智谱和小米均无公开 API Key 查询余量接口，需从浏览器 Network 面板复制完整 Cookie（含 HttpOnly 的 serviceToken）

## [0.3.0] - 2026-06-08

### Added
- **Hermes Windows 采集器**：新增 `hermes-win` agent，采集 Windows 本地 `%LOCALAPPDATA%\hermes\state.db`，与 WSL 版 `hermes` 采集器独立运行、互不干扰
- **缓存率分析图表**：新增缓存命中率分析模块，支持按 Agent / 按模型 / Agent×模型 三种维度查看

### Fixed
- **WSL Hermes stat 路径**：在 Windows 上 stat `/root/.hermes/state.db`（Linux 路径）失败导致采集器直接退出，改为使用 UNC 路径 stat 并降级到 `wsl_copy_to_tmp`
- **缓存率图表 tooltip 错位**：`buildAgentOption` / `buildModelOption` 中 `reverse()` 原地翻转数组导致 tooltip 显示的名称与 Y 轴不匹配
- **Agent×模型柱状图叠压**：多模型 series 的 `barWidth` 过大导致柱子叠在一起，改为堆叠柱状图 + 动态高度
- **Agent 白名单遗漏**：`SUPPORTED_AGENTS` 和 FilterBar 颜色映射缺少 `hermes-win`

## [0.2.0] - 2026-05-28

### Added
- **人民币显示**: 所有费用从美元改为人民币（汇率 7.25），编辑定价时直接输入人民币
- **一键更新定价**: 模型定价页面新增"一键更新定价"按钮，从 OpenRouter API 获取最新价格
- **分页与搜索**: 使用记录和模型定价表支持分页（10/20/50 条/页）和搜索
- **POST /api/pricing/refresh**: 新增后端 API 端点，批量更新模型定价

### Fixed
- **Hermes 采集器 WAL 修复**: 复制 state.db 时同步复制 WAL/SHM 文件，解决数据陈旧问题
- **时间戳修正**: Open session 使用当前时间作为 timestamp，不再归到 session 创建时间
- **表头对齐**: 修复使用记录和模型定价表的表头与数据列不对齐问题
- **UNIQUE INDEX**: 从 `(timestamp, agent, session_id, model)` 改为 `(agent, session_id, model)`，避免重复记录

### Changed
- 模型定价 upsert key 不再包含 timestamp，每次更新覆盖同一条记录

## [0.1.0] - 2026-05-01

### Added
- 初始版本发布
- 多 Agent 支持：Claude Code、Hermes、OpenClaw、OpenClaude
- 实时仪表盘（SSE 推送）
- ECharts 图表：趋势图、饼图、条形图
- 时间范围筛选：今日 / 7 天 / 30 天 / 自定义
- 模型定价管理（YAML 配置 + 热更新）
- CSV 导出
- FastAPI + Svelte 5 + SQLite 架构
