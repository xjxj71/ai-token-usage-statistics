# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **项目维度分析**：新增 `token_usage.project` 列（取会话工作目录最后一段），`/api/summary?group_by=project` 聚合 + 前端"项目消耗分布"条形图 + FilterBar 项目多选筛选 + `/api/projects` 端点（数据来自 claude-code / openclaude / zcode）
- **思考 Token 统计**：新增 `token_usage.reasoning_tokens` 列（zcode / opencode / mimocode 采集），第 8 张统计卡、使用记录"思考"列、CSV 导出、会话与摘要中的思考 Token 汇总
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

### Security
- 凭据配置 `config/quota_providers.yaml` 移出 git 跟踪，提供 `quota_providers.example.yaml` 模板
- `PUT /api/quota/config` 仅允许本机调用（或携带有效 `X-API-Key`），响应不再回显 session token
- CORS 默认来源收紧为本地开发服务器

### Fixed
- 修复 OpenClaude 采集器被误改为 `openclaw` 导致的采集中断与数据混淆
- custom 时间范围 `to` 日期整天纳入统计；非法 range 返回 400 而非静默回退
- SSE 改为每客户端队列，消除多客户端通知丢失
- 采集器状态文件损坏时自动重置而非每轮崩溃
- 采集循环中的阻塞 IO（wsl.exe、UNC 复制、JSONL 扫描、SQLite、YAML）全部移入线程池
- 筛选栏 agent/模型列表改为随 SSE 实时刷新——页面打开期间新出现的 agent 自动进入筛选栏，无需手动刷新页面
- 修复新模型自动入库时一律以 0 价插入、挡住 YAML 已配置定价的问题（`glm-5.3` 费用显示为 0 的根因）；已有 0 价行可通过定价表或 API 修正

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
