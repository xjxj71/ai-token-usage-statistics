# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
