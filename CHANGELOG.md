# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
