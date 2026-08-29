"""Daily / weekly usage report — one endpoint composing existing aggregates.

The report is computed live on request (no scheduling, no persistence):
totals with period-over-period deltas, top agents / models / projects, and
a quota overview, plus a ready-to-copy Markdown rendering.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from backend.api.constants import IGNORED_MODELS
from backend.api.range_utils import previous_window, resolve_range
from backend.api.summary import _totals
from backend.db import database as db_module
from backend.db.models import SummaryRow, fetch_summary

logger = logging.getLogger(__name__)

router = APIRouter(tags=["report"])

_RANGE_LABELS = {"today": "今日", "7d": "近 7 天", "30d": "近 30 天"}


def _row_tokens(r: SummaryRow) -> int:
    return r.input_tokens + r.output_tokens + r.cache_read_tokens + r.cache_write_tokens


def _row_dict(r: SummaryRow) -> dict:
    return {
        "name": r.agent or r.model or r.project,
        "total_tokens": _row_tokens(r),
        "cost_usd": r.cost_usd,
        "call_count": r.call_count,
    }


def _fmt_tokens(n: int) -> str:
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return str(n)


def _delta_str(cur: float, prev: float) -> str:
    if prev <= 0:
        return "—"
    pct = (cur - prev) / prev * 100
    return f"{'+' if pct >= 0 else ''}{pct:.1f}%"


def _build_markdown(
    label: str,
    totals: dict,
    previous: dict,
    top_agents: list[dict],
    top_models: list[dict],
    top_projects: list[dict],
    quota: list[dict],
    usd_to_cny: float,
) -> str:
    lines = [f"# AI Token 用量报告 · {label}", ""]
    lines.append(f"- 总消耗：**{_fmt_tokens(totals['total_tokens'])}** tokens（环比 {_delta_str(totals['total_tokens'], previous['total_tokens'])}）")
    lines.append(f"- 思考 Token：{_fmt_tokens(totals['reasoning_tokens'])}")
    lines.append(f"- 费用：约 **¥{totals['cost_usd'] * usd_to_cny:.2f}**（环比 {_delta_str(totals['cost_usd'], previous['cost_usd'])}）")
    lines.append(f"- 请求次数：{totals['call_count']}（环比 {_delta_str(totals['call_count'], previous['call_count'])}）")

    def _section(title: str, items: list[dict]) -> list[str]:
        if not items:
            return [f"## {title}", "（暂无数据）", ""]
        out = [f"## {title}"]
        for i, it in enumerate(items, 1):
            out.append(f"{i}. **{it['name']}** — {_fmt_tokens(it['total_tokens'])} tokens · ${it['cost_usd']:.4f} · {it['call_count']} 次")
        out.append("")
        return out

    lines.append("")
    lines.extend(_section("Top Agent（按 Token）", top_agents))
    lines.extend(_section("Top 模型（按费用）", top_models))
    lines.extend(_section("Top 项目（按 Token）", top_projects))

    if quota:
        lines.append("## 套餐余量")
        for q in quota:
            if q["total"]:
                pct = q["used"] / q["total"] * 100 if q["total"] else 0
                lines.append(f"- {q['display_name']}（{q['plan_name']}）：已用 {pct:.0f}%（{_fmt_tokens(int(q['used']))} / {_fmt_tokens(int(q['total']))} {q['unit']}）")
            else:
                lines.append(f"- {q['display_name']}（{q['plan_name']}）：暂无数据（{q['source']}）")
        lines.append("")

    return "\n".join(lines).strip()


@router.get("/report")
async def get_report(
    range_key: str = Query("today", alias="range"),
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    agent: str | None = Query(None),
    model: str | None = Query(None),
    project: str | None = Query(None),
):
    db = await db_module.get_db()
    from_ts, to_ts = resolve_range(range_key, from_date, to_date)

    agents = agent.split(",") if agent else None
    models = model.split(",") if model else None
    projects = project.split(",") if project else None

    async def fetch_group(a_from: str, a_to: str, group_by: str) -> list[SummaryRow]:
        return await fetch_summary(
            db, agents=agents, models=models, projects=projects,
            from_ts=a_from, to_ts=a_to, group_by=group_by,
        )

    by_agent = await fetch_group(from_ts, to_ts, "agent")
    by_model = await fetch_group(from_ts, to_ts, "model")
    by_project = await fetch_group(from_ts, to_ts, "project")

    totals = _totals(by_agent)
    prev_from, prev_to = previous_window(from_ts, to_ts)
    previous = _totals(await fetch_group(prev_from, prev_to, "agent"))

    top_agents = [_row_dict(r) for r in sorted(by_agent, key=_row_tokens, reverse=True)[:3]]
    top_models = [
        _row_dict(r)
        for r in sorted(
            (r for r in by_model if r.model.lower() not in IGNORED_MODELS),
            key=lambda r: r.cost_usd, reverse=True,
        )[:3]
    ]
    top_projects = [_row_dict(r) for r in sorted((r for r in by_project if r.project), key=_row_tokens, reverse=True)[:3]]

    # Quota overview — best effort; a broken provider must not break the report
    quota: list[dict] = []
    try:
        from backend.quota.registry import get_registry

        for s in await get_registry().fetch_all():
            main = s.main_window
            quota.append({
                "provider": s.provider,
                "display_name": s.display_name,
                "plan_name": s.plan_name,
                "source": s.source,
                "used": main.used if main else None,
                "total": main.total if main else None,
                "remaining": main.remaining if main else None,
                "unit": main.unit if main else "",
                "reset_at": main.reset_at if main else None,
            })
    except Exception as e:  # noqa: BLE001
        logger.warning("Quota overview unavailable for report: %s", e)

    label = _RANGE_LABELS.get(range_key, f"{from_ts[:10]} ~ {to_ts[:10]}")
    from backend.exchange_rate import get_rate

    usd_to_cny = (await get_rate()).rate
    markdown = _build_markdown(
        label, totals, previous, top_agents, top_models, top_projects, quota, usd_to_cny
    )

    return {
        "range": range_key,
        "label": label,
        "from": from_ts,
        "to": to_ts,
        "totals": totals,
        "previous": previous,
        "top_agents": top_agents,
        "top_models": top_models,
        "top_projects": top_projects,
        "quota": quota,
        "markdown": markdown,
    }
