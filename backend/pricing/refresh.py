"""模型定价刷新：OpenRouter 目录匹配 + 每日自动更新 + 未计价记录补齐。

用户约定的规则：
- 价格每天自动更新一次（本地日期）；当天若手动刷新过，则不再自动更新。
- 手动在定价表编辑过的行（price_source='manual'）不被自动刷新覆盖；
  手动「一键更新」是显式动作，可覆盖全部匹配行。
- 已计算的成本锁定：只有「刚获得真实价格」的模型的 cost_usd=0 记录会被
  补齐；任何非零历史成本不随后续价格变动重算。

模型名匹配：OpenRouter id 带供应商前缀（anthropic/claude-sonnet-4.5），
本库模型名为去前缀形式，故用「全名 / 去前缀 / 去 :variant 后缀」多键匹配。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from backend import paths
from backend.db import database as db_module

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 3600   # 每小时检查一次是否该跑当日刷新
_RETRY_GAP_SECONDS = 1800        # 失败后至少隔 30 分钟再试
_refresh_task: asyncio.Task | None = None


def _state_path():
    return paths.data_dir() / "pricing_refresh.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    try:
        _state_path().write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        logger.warning("无法持久化定价刷新状态", exc_info=True)


def _local_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _fetch_catalog() -> dict[str, dict[str, float]]:
    """OpenRouter 目录 → {候选模型名: 每 M token 价格}。"""
    import urllib.request

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"User-Agent": "ai-token-usage/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    entries: list[tuple[str, dict[str, float]]] = []
    for m in data.get("data", []):
        mid = (m.get("id") or "").lower()
        pricing = m.get("pricing") or {}
        if not mid or not pricing:
            continue
        try:
            prices = {
                "input": float(pricing.get("prompt", 0)) * 1_000_000,
                "output": float(pricing.get("completion", 0)) * 1_000_000,
                "cache_read": float(pricing.get("input_cache_read", 0)) * 1_000_000,
                "cache_write": float(pricing.get("input_cache_write", 0)) * 1_000_000,
            }
        except (TypeError, ValueError):
            continue
        if not any(prices.values()):
            continue
        entries.append((mid, prices))

    # 先收录无 :variant 后缀的基础 id，避免 :free/:extended 抢占同名键
    entries.sort(key=lambda e: ":" in e[0])
    catalog: dict[str, dict[str, float]] = {}
    for mid, prices in entries:
        base = mid.split(":")[0]
        for key in (base, base.split("/")[-1]):
            catalog.setdefault(key, prices)
    return catalog


async def refresh_pricing_core(*, manual: bool) -> dict:
    """拉取 OpenRouter 最新价格，更新定价表并补齐未计价记录。

    范围 = 定价表已有模型 ∪ token_usage 出现过的模型（新模型也能拿到价）。
    """
    db = await db_module.get_db()
    catalog = await asyncio.to_thread(_fetch_catalog)

    rows = await db.execute_fetchall(
        """SELECT model, input_price, output_price, cache_read_price,
                  cache_write_price, price_source FROM model_pricing"""
    )
    used = await db.execute_fetchall("SELECT DISTINCT model FROM token_usage")
    existing = {r["model"].lower(): r for r in rows}
    targets = set(existing) | {r["model"].lower() for r in used}

    now = datetime.now(UTC).isoformat()
    updates: list[tuple] = []
    inserts: list[tuple] = []
    newly_priced: dict[str, dict[str, float]] = {}

    for name in sorted(targets):
        prices = catalog.get(name)
        if not prices:
            continue
        row = existing.get(name)
        if row is None:
            inserts.append(
                (name, prices["input"], prices["output"],
                 prices["cache_read"], prices["cache_write"], now, "api")
            )
            newly_priced[name] = prices
            continue
        # 自动刷新尊重用户手动编辑；手动一键刷新是显式覆盖
        if not manual and row["price_source"] == "manual":
            continue
        cur = (row["input_price"], row["output_price"],
               row["cache_read_price"], row["cache_write_price"])
        new = (prices["input"], prices["output"],
               prices["cache_read"], prices["cache_write"])
        if cur == new:
            continue
        updates.append((*new, now, "api", row["model"]))
        if not any(cur) and any(new):
            newly_priced[row["model"].lower()] = prices

    if updates:
        await db.executemany(
            """UPDATE model_pricing
               SET input_price = ?, output_price = ?, cache_read_price = ?,
                   cache_write_price = ?, updated_at = ?, price_source = ?
               WHERE model = ?""",
            updates,
        )
    if inserts:
        await db.executemany(
            """INSERT INTO model_pricing
               (model, input_price, output_price, cache_read_price,
                cache_write_price, updated_at, price_source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            inserts,
        )

    # 补齐：仅「刚拿到真实价格」的模型的历史 0 成本记录；非零成本锁定不动
    backfilled = 0
    for model, prices in newly_priced.items():
        params = (
            prices["input"], prices["output"],
            prices["cache_read"], prices["cache_write"], model,
        )
        # hanako 存的是供应商上报成本，0 可能是真实 0（免费额度），
        # 不能用目录价回填 —— 与 data_migrations.REPORTED_COST_AGENTS 一致。
        # hermes/openclaw 的 0 必为「当时无价算出的 0」（有实际花费会优先存），可回填。
        cur = await db.execute(
            """UPDATE token_usage
               SET cost_usd = ROUND((input_tokens * ? + output_tokens * ?
                     + cache_read_tokens * ? + cache_write_tokens * ?) / 1000000.0, 6)
               WHERE model = ? AND cost_usd = 0 AND agent != 'hanako'""",
            params,
        )
        backfilled += cur.rowcount or 0
        await db.execute(
            """UPDATE usage_daily
               SET cost_usd = ROUND((input_tokens * ? + output_tokens * ?
                     + cache_read_tokens * ? + cache_write_tokens * ?) / 1000000.0, 6)
               WHERE model = ? AND cost_usd = 0 AND agent != 'hanako'""",
            params,
        )

    if updates or inserts or backfilled:
        await db.commit()
        await db_module.sync_pricing_from_db(db)

    state = _load_state()
    if manual:
        state["last_manual_at"] = now
    else:
        state["last_auto_date"] = _today()
        state["last_auto_at"] = now
    result = {
        "updated": len(updates),
        "added": len(inserts),
        "backfilled_records": backfilled,
        "backfilled_models": sorted(newly_priced),
        "at": now,
        "manual": manual,
    }
    state["last_result"] = result
    _save_state(state)
    logger.info(
        "Pricing refresh (%s): updated=%d added=%d backfilled=%d",
        "manual" if manual else "auto", len(updates), len(inserts), backfilled,
    )
    return result


async def maybe_auto_refresh() -> dict | None:
    """当日未跑过且当天无手动刷新时执行自动刷新；失败按间隔重试。"""
    state = _load_state()
    today = _today()
    if state.get("last_auto_date") == today:
        return None
    if _local_date(state.get("last_manual_at")) == today:
        return None
    last_attempt = state.get("last_attempt_at")
    if last_attempt:
        try:
            elapsed = (datetime.now(UTC) - datetime.fromisoformat(last_attempt)).total_seconds()
            if elapsed < _RETRY_GAP_SECONDS:
                return None
        except ValueError:
            pass
    state["last_attempt_at"] = datetime.now(UTC).isoformat()
    _save_state(state)
    try:
        return await refresh_pricing_core(manual=False)
    except Exception:
        logger.exception("每日定价自动刷新失败")
        return None


def get_status() -> dict:
    state = _load_state()
    today = _today()
    return {
        "last_auto_date": state.get("last_auto_date"),
        "last_auto_at": state.get("last_auto_at"),
        "last_manual_at": state.get("last_manual_at"),
        "last_result": state.get("last_result"),
        "auto_pending_today": (
            state.get("last_auto_date") != today
            and _local_date(state.get("last_manual_at")) != today
        ),
    }


async def _refresh_loop() -> None:
    while True:
        try:
            await maybe_auto_refresh()
        except Exception:
            logger.exception("Pricing refresh loop error")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)


def start_pricing_loop() -> bool:
    global _refresh_task
    if _refresh_task is not None and not _refresh_task.done():
        return False
    _refresh_task = asyncio.get_running_loop().create_task(_refresh_loop())
    return True


def stop_pricing_loop() -> None:
    global _refresh_task
    if _refresh_task is not None:
        _refresh_task.cancel()
        _refresh_task = None