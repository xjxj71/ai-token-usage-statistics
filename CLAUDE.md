# AI Token Usage Statistics

Token usage tracking and analysis for AI coding assistants (Claude Code, OpenClaw, Hermes, Hermes-Win, OpenClaude, Codex, Qoder).

## Project Structure

```
ai-token-usage-statistics/
├── backend/
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # pydantic-settings 配置
│   ├── api/                 # REST + SSE 接口
│   ├── collectors/          # 各 Agent 数据采集器
│   ├── db/                  # SQLite 连接与表结构
│   ├── pricing/             # 模型定价与费用计算
│   └── quota/               # 套餐余量监控（Zhipu、Xiaomi）
├── frontend/
│   └── src/
│       ├── App.svelte       # 主应用组件
│       ├── components/      # StatCard, TrendChart, PlanQuotaCard 等
│       ├── api/             # 请求封装 + SSE 客户端
│       └── types/           # TypeScript 类型定义
├── tests/                   # pytest 测试用例
├── config/                  # 模型定价 YAML + 套餐 Provider 配置
├── scripts/                 # 工具脚本（费用重算等）
├── docs/                    # 设计文档、配置指南
└── pyproject.toml           # Python 项目配置
```

## Quick Start

```bash
# Backend
pip install -e .
python -m uvicorn backend.main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```

## Key Commands

- `npm run dev` - Start frontend dev server
- `npm run build` - Build frontend
- `pytest` - Run Python tests

## 数据口径约定（`token_usage`）

所有采集器入库的行口径一致，任何统计直接按行求和即可：

- `input_tokens` 恒为**未命中缓存**的输入；缓存读/写各归 `cache_read_tokens` / `cache_write_tokens`。源工具给出"完整提示词长度"的（ZCode、Codex、Qoder），采集器入库前换算。
- 每一行都是**真实增量**，不是会话累计快照。Hermes 的源库是会话累计值：进行中的会话每小时写一行增量（由状态里的 `session_marks` 推导，重复轮询重写同样的绝对值，所以状态损坏也不会重复计数），会话结束时删掉该会话的全部行、合并成一行总量（`TokenRecord.replace_session`）。
- 费用：`cost_usd` = token × **定价表**（`model_pricing` 表，前端可编辑、可从 OpenRouter 刷新，`overlay_pricing()` 让它成为运行时计价依据）；`config/model_pricing.yaml` 只是内置默认价和首次种子。定价表里全 0 的行是占位行，YAML 有价即自动跟进。hanako / openclaw / Hermes 可能存的是供应商上报的实际花费，重算费用时不能覆盖。
- 改动采集器口径时，同步在 `backend/db/data_migrations.py` 提供一次性迁移（按 `PRAGMA user_version` 门控，迁移前自动留备份），并在真实库的副本上演练后再发布。验证数据相关逻辑要用安装版的真实库 `%APPDATA%\ai-token-usage\data\token_statistic.db`——仓库里的 `data/` 是另一份开发库，agent 构成不同。

## 套餐余量监控

支持查询大模型套餐剩余用量，当前支持：
- **智谱 GLM Coding Plan**（Lite/Pro/Max，5小时窗口 + 周额度；2026-07-30 起为积分制，接口返回 `CREDIT_LIMIT` 时自动识别，历史 V2 prompt 制返回 `TOKENS_LIMIT`）
- **小米 MiMo Token Plan**（Lite/Standard/Pro/Max，月度 Credits）

套餐卡片底部展示各模型的消耗倍率（积分抵扣系数「输入/缓存/输出」或 prompt 消耗倍率，含非高峰/夜间折扣与生效时段，官方标注的限时活动带「限时」角标）。模型与倍率数据由 `backend/quota/multipliers.py` 自动从官方文档中心同步（智谱 `docs.bigmodel.cn/cn/coding-plan/*.md`、小米 `mimo.mi.com/static/docs/...`，启动时 + 每 6h 刷新，`POST /api/quota/multipliers/refresh` 可手动刷新），失败时回退到本地缓存与内置快照。官方改价常用「~~旧值~~ 新值」删除线标记，解析前会先规范化这类编辑标记；若某次解析比上次少了模型，仍会应用更新但会在日志里留 WARNING（可能是官方下线/改名，也可能是页面格式又变了）。

配置方式：编辑 `config/quota_providers.yaml`，或在前端"设置"面板中填写。

---

<!-- superpowers-zh:begin (do not edit between these markers) -->
# Superpowers-ZH 中文增强版

本项目已安装 superpowers-zh 技能框架（20 个 skills）。

## 核心规则

1. **收到任务时，先检查是否有匹配的 skill** — 哪怕只有 1% 的可能性也要检查
2. **设计先于编码** — 收到功能需求时，先用 brainstorming skill 做需求分析
3. **测试先于实现** — 写代码前先写测试（TDD）
4. **验证先于完成** — 声称完成前必须运行验证命令

## 可用 Skills

Skills 位于 `.claude/skills/` 目录，每个 skill 有独立的 `SKILL.md` 文件。

- **brainstorming**: 在任何创造性工作之前必须使用此技能——创建功能、构建组件、添加功能或修改行为。在实现之前先探索用户意图、需求和设计。
- **chinese-code-review**: 中文 review 沟通参考——话术模板、分级标注（必须修复/建议修改/仅供参考）、国内团队常见反模式应对。仅在用户显式 /chinese-code-review 时调用，不要根据上下文自动触发。
- **chinese-commit-conventions**: 中文 commit 与 changelog 配置参考——Conventional Commits 中文适配、commitlint/husky/commitizen 中文模板、conventional-changelog 中文配置。仅在用户显式 /chinese-commit-conventions 时调用，不要根据上下文自动触发。
- **chinese-documentation**: 中文文档排版参考——中英文空格、全半角标点、术语保留、链接格式、中文文案排版指北约定。仅在用户显式 /chinese-documentation 时调用，不要根据上下文自动触发。
- **chinese-git-workflow**: 国内 Git 平台配置参考——Gitee、Coding.net、极狐 GitLab、CNB 的 SSH/HTTPS/凭据/CI 接入差异与镜像同步配置。仅在用户显式 /chinese-git-workflow 时调用，不要根据上下文自动触发。
- **dispatching-parallel-agents**: 当面对 2 个以上可以独立进行、无共享状态或顺序依赖的任务时使用
- **executing-plans**: 当你有一份书面实现计划需要在单独的会话中执行，并设有审查检查点时使用
- **finishing-a-development-branch**: 当实现完成、所有测试通过、需要决定如何集成工作时使用——通过提供合并、PR 或清理等结构化选项来引导开发工作的收尾
- **mcp-builder**: MCP 服务器构建方法论 — 系统化构建生产级 MCP 工具，让 AI 助手连接外部能力
- **receiving-code-review**: 收到代码审查反馈后、实施建议之前使用，尤其当反馈不明确或技术上有疑问时——需要技术严谨性和验证，而非敷衍附和或盲目执行
- **requesting-code-review**: 完成任务、实现重要功能或合并前使用，用于验证工作成果是否符合要求
- **subagent-driven-development**: 当在当前会话中执行包含独立任务的实现计划时使用
- **systematic-debugging**: 遇到任何 bug、测试失败或异常行为时使用，在提出修复方案之前执行
- **test-driven-development**: 在实现任何功能或修复 bug 时使用，在编写实现代码之前
- **using-git-worktrees**: 当需要开始与当前工作区隔离的功能开发或执行实现计划之前使用——创建具有智能目录选择和安全验证的隔离 git 工作树
- **using-superpowers**: 在开始任何对话时使用——确立如何查找和使用技能，要求在任何响应（包括澄清性问题）之前调用 Skill 工具
- **verification-before-completion**: 在宣称工作完成、已修复或测试通过之前使用，在提交或创建 PR 之前——必须运行验证命令并确认输出后才能声称成功；始终用证据支撑断言
- **workflow-runner**: 在 Claude Code / OpenClaw / Cursor 中直接运行 agency-orchestrator YAML 工作流——无需 API key，使用当前会话的 LLM 作为执行引擎。当用户提供 .yaml 工作流文件或要求多角色协作完成任务时触发。
- **opendesign**: 设计页面/原型/PPT/移动端界面/仪表盘/落地页等视觉设计制品时使用。基于 Open Design 开源项目，提供 132 个设计 Skills 和 150 个品牌设计系统。
- **writing-plans**: 当你有规格说明或需求用于多步骤任务时使用，在动手写代码之前
- **writing-skills**: 当创建新技能、编辑现有技能或在部署前验证技能是否有效时使用

## 如何使用

当任务匹配某个 skill 时，使用 `Skill` 工具加载对应 skill 并严格遵循其流程。绝不要用 Read 工具读取 SKILL.md 文件。

如果你认为哪怕只有 1% 的可能性某个 skill 适用于你正在做的事情，你必须调用该 skill 检查。
<!-- superpowers-zh:end -->
