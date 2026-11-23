"""Model consumption multipliers, auto-refreshed from the vendors' docs.

每个套餐供应商的模型消耗倍率（抵扣系数 / 消耗倍率）都写在其官方文档中心。
This module keeps a fresh local copy by fetching and parsing those pages on
a timer, mirroring the live-cache-persist-fallback pattern of
:mod:`backend.exchange_rate`:

* 智谱 GLM Coding Plan —
  ``docs.bigmodel.cn/cn/coding-plan/overview.md``（积分抵扣系数 + 积分额度）
  与 ``.../notice/usage-revision.md``（历史 V2 版 prompt 消耗倍率 + prompts
  额度）；``docs.z.ai`` 提供同构英文页作为备用源。
* 小米 MiMo Token Plan —
  ``mimo.mi.com/static/docs/tokenplan/Token Plan/subscription.md``。

Read resolution order (see :func:`get_set`):

1. In-memory cache refreshed in the background (on startup, every
   ``_REFRESH_INTERVAL_SECONDS``, or via ``POST /api/quota/multipliers/refresh``).
2. ``data/model_multipliers.json`` persisted at the last successful fetch
   (offline start).
3. Built-in defaults — a frozen snapshot of the official pages.

Fetch/parse failures never raise; callers always get a usable set whose
``source`` marker says where the data came from ("live" / "cache" / "defaults").
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from backend import paths
from backend.quota.base import ModelMultiplier

logger = logging.getLogger(__name__)

_FETCH_TIMEOUT = 15
_REFRESH_INTERVAL_SECONDS = 12 * 3600  # docs pages change rarely; 12h is plenty

# Date the built-in defaults were verified against the official pages.
_DEFAULTS_AS_OF = "2026-11-24T00:00:00+08:00"


def _ts(value: str) -> datetime:
    """Parse an ISO timestamp for comparison; unparsable → ancient."""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=UTC)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ── Data shapes ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class MultiplierSet:
    """Complete multiplier + plan-limit snapshot for one provider/mode."""

    provider: str                          # "zhipu" | "xiaomi"
    mode: str                              # "credits" | "prompts"
    models: tuple[ModelMultiplier, ...]
    plan_limits: dict[str, dict[str, float]]  # plan_type -> window -> total
    note: str                              # UI 说明（单位、折扣、高峰时段）
    source: str = "defaults"               # "live" | "cache" | "defaults"
    fetched_at: str = ""                   # ISO-8601 of the docs fetch
    source_url: str = ""

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.mode}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "mode": self.mode,
            "models": [m.to_dict() for m in self.models],
            "plan_limits": self.plan_limits,
            "note": self.note,
            "source": self.source,
            "fetched_at": self.fetched_at,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MultiplierSet:
        limits: dict[str, dict[str, float]] = {}
        for plan, windows in (d.get("plan_limits") or {}).items():
            if isinstance(windows, dict):
                limits[str(plan)] = {
                    str(k): float(v) for k, v in windows.items() if v is not None
                }
        return cls(
            provider=str(d.get("provider", "")),
            mode=str(d.get("mode", "")),
            models=tuple(ModelMultiplier.from_dict(m) for m in d.get("models") or []),
            plan_limits=limits,
            note=str(d.get("note") or ""),
            source=str(d.get("source") or "cache"),
            fetched_at=str(d.get("fetched_at") or ""),
            source_url=str(d.get("source_url") or ""),
        )


@dataclass
class _Parsed:
    """Result of parsing one documentation page."""

    mode: str
    models: list[ModelMultiplier] = field(default_factory=list)
    plan_limits: dict[str, dict[str, float]] = field(default_factory=dict)
    note: str = ""


# ── Built-in defaults (frozen snapshot of the official pages) ───────


def _default_sets() -> dict[str, MultiplierSet]:
    zhipu_credits = MultiplierSet(
        provider="zhipu",
        mode="credits",
        models=(
            ModelMultiplier(
                model="glm-5.4", peak=1.0, off_peak=0.5, peak_hours="14-18",
                off_peak_label="非高峰", input_rate=4.6, cached_rate=1.1,
                output_rate=16.0, rate_unit="积分/万Token",
            ),
            ModelMultiplier(
                model="glm-5.3", peak=1.0, off_peak=0.5, peak_hours="14-18",
                off_peak_label="非高峰", input_rate=6.9, cached_rate=1.7,
                output_rate=24.0, rate_unit="积分/万Token",
            ),
            ModelMultiplier(
                model="glm-5.3-flash", peak=1.0, off_peak=0.5, peak_hours="14-18",
                off_peak_label="非高峰", input_rate=2.3, cached_rate=0.56,
                output_rate=8.0, rate_unit="积分/万Token",
            ),
        ),
        plan_limits={
            "lite": {"window_5h": 2_000, "weekly": 10_000},
            "pro": {"window_5h": 12_000, "weekly": 60_000},
            "max": {"window_5h": 28_000, "weekly": 140_000},
        },
        note=(
            "输入/缓存/输出 = 每万 Token 抵扣积分 · 非高峰（周一至五 14-18 以外"
            "及周末）0.5x · 高峰：周一至五 14-18（UTC+8）"
        ),
        fetched_at=_DEFAULTS_AS_OF,
        source_url="https://docs.bigmodel.cn/cn/coding-plan/overview.md",
    )

    zhipu_prompts = MultiplierSet(
        provider="zhipu",
        mode="prompts",
        models=(
            ModelMultiplier(
                model="glm-5.4", peak=2.0, off_peak=0.67, peak_hours="14-18",
                off_peak_label="非高峰",
            ),
            ModelMultiplier(
                model="glm-5.3", peak=3.0, off_peak=1.0, peak_hours="14-18",
                off_peak_label="非高峰",
            ),
            ModelMultiplier(
                model="glm-5.3-flash", peak=1.2, off_peak=0.4, peak_hours="14-18",
                off_peak_label="非高峰",
            ),
        ),
        plan_limits={
            "lite": {"window_5h": 80, "weekly": 400},
            "pro": {"window_5h": 400, "weekly": 2_000},
            "max": {"window_5h": 1_600, "weekly": 8_000},
        },
        note=(
            "每 prompt 消耗倍率（历史 V2 套餐）· 高峰：周一至五 14-18（UTC+8）"
        ),
        fetched_at=_DEFAULTS_AS_OF,
        source_url="https://docs.bigmodel.cn/cn/coding-plan/notice/usage-revision.md",
    )

    xiaomi_credits = MultiplierSet(
        provider="xiaomi",
        mode="credits",
        models=(
            ModelMultiplier(
                model="mimo-v2.6-pro", peak=1.0, off_peak=0.8, peak_hours="08-24",
                off_peak_label="夜间", input_rate=300.0, cached_rate=2.5,
                output_rate=600.0, rate_unit="Credits/Token",
            ),
            ModelMultiplier(
                model="mimo-v2.6-flash", peak=1.0, off_peak=0.8, peak_hours="08-24",
                off_peak_label="夜间", input_rate=100.0, cached_rate=2.0,
                output_rate=200.0, rate_unit="Credits/Token",
            ),
            ModelMultiplier(
                model="mimo-v2.6-pro-ultraspeed", peak=1.0, off_peak=0.8,
                peak_hours="08-24", off_peak_label="夜间", input_rate=3000.0,
                cached_rate=25.0, output_rate=6000.0, rate_unit="Credits/Token",
            ),
        ),
        plan_limits={
            "lite": {"monthly": 4_100_000_000.0},
            "standard": {"monthly": 11_000_000_000.0},
            "pro": {"monthly": 38_000_000_000.0},
            "max": {"monthly": 82_000_000_000.0},
        },
        note="输入/缓存/输出 = Credits/Token · 夜间（00-08）0.8x",
        fetched_at=_DEFAULTS_AS_OF,
        source_url="https://mimo.mi.com/static/docs/tokenplan/Token%20Plan/subscription.md",
    )

    return {s.key: s for s in (zhipu_credits, zhipu_prompts, xiaomi_credits)}


# ── Documentation sources & parsers ─────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")


def _flatten(text: str) -> str:
    """Strip HTML tags — the doc pages mix markdown and raw HTML tables."""
    return _TAG_RE.sub(" ", text)


def _num_list(flat: str, anchor: str, unit_pat: str, count: int) -> list[float] | None:
    """Extract ``count`` numbers of ``unit_pat`` following an anchor keyword."""
    gap = r"[^0-9]*?"
    pat = re.escape(anchor) + "".join(
        gap + r"([\d.]+)\s*" + unit_pat for _ in range(count)
    )
    m = re.search(pat, flat)
    if not m:
        return None
    return [float(m.group(i)) for i in range(1, count + 1)]


def _zhipu_peak_window(text: str) -> str | None:
    """'14-18' from 高峰时段：每周一至周五的 14:00～18:00 / Monday-Friday 14:00–18:00."""
    m = re.search(
        r"高峰(?:时段|期)[^0-9]{0,40}(\d{1,2})[：:]\d{2}\s*[～~–—-]\s*(\d{1,2})[：:]\d{2}",
        text,
    )
    if m:
        return f"{int(m.group(1))}-{int(m.group(2))}"
    m = re.search(
        r"Monday to Friday,\s*(\d{1,2}):\d{2}\s*[–—-]\s*(\d{1,2}):\d{2}", text
    )
    if m:
        return f"{int(m.group(1))}-{int(m.group(2))}"
    return None


def _zhipu_credit_note(off_peak: float, peak_hours: str) -> str:
    return (
        f"输入/缓存/输出 = 每万 Token 抵扣积分 · 非高峰 {off_peak:g}x · "
        f"高峰：周一至五 {peak_hours}（UTC+8）"
    )


def _zhipu_prompt_note(peak_hours: str) -> str:
    return f"每 prompt 消耗倍率（历史 V2 套餐）· 高峰：周一至五 {peak_hours}（UTC+8）"


#  <td>GLM-5.4</td><td>4.6</td><td>1.1</td><td>16</td>  （名称可带括号注释）
_ZHIPU_MODEL_ROW_RE = re.compile(
    r"<td[^>]*>\s*(GLM-[0-9][\w.\-]*)[^<]*</td>\s*"
    r"<td[^>]*>\s*(\d+(?:\.\d+)?)\s*</td>\s*"
    r"<td[^>]*>\s*(\d+(?:\.\d+)?)\s*</td>\s*"
    r"<td[^>]*>\s*(\d+(?:\.\d+)?)\s*</td>",
    re.IGNORECASE,
)


def _parse_zhipu_overview(text: str) -> _Parsed | None:
    """Parse the GLM Coding Plan overview page (credit coefficient table)."""
    models = []
    for m in _ZHIPU_MODEL_ROW_RE.finditer(text):
        models.append(ModelMultiplier(
            model=m.group(1).lower(),
            peak=1.0, off_peak=1.0, peak_hours="14-18", off_peak_label="非高峰",
            input_rate=float(m.group(2)), cached_rate=float(m.group(3)),
            output_rate=float(m.group(4)), rate_unit="积分/万Token",
        ))
    if not models:
        return None

    # 非高峰时段内，模型调用按基础积分消耗的 50% 抵扣 /
    # charged at 50% of the standard credit rate
    off_peak = 0.5
    m = re.search(
        r"非高峰时段内[^。\n]*?按基础积分消耗的\s*(\d+(?:\.\d+)?)\s*%", text
    ) or re.search(
        r"charged at\s*(\d+(?:\.\d+)?)\s*%\s*of the standard credit rate", text, re.IGNORECASE
    )
    if m:
        off_peak = float(m.group(1)) / 100.0
    for model in models:
        model.off_peak = off_peak

    peak_hours = _zhipu_peak_window(text) or "14-18"

    limits: dict[str, dict[str, float]] = {}
    for m in re.finditer(
        r"\|\s*(Lite|Pro|Max)(?:\s*(?:套餐|Plan))?\s*\|\s*([\d,]+)\s*\|\s*([\d,]+)\s*\|",
        text,
        re.IGNORECASE,
    ):
        limits[m.group(1).lower()] = {
            "window_5h": float(m.group(2).replace(",", "")),
            "weekly": float(m.group(3).replace(",", "")),
        }

    parsed = _Parsed(mode="credits", models=models, plan_limits=limits)
    parsed.note = _zhipu_credit_note(off_peak, peak_hours)
    return parsed


# **GLM-5.4**：调用时将按照 “非高峰期 0.67 倍，高峰期 2 倍” 系数消耗额度。
_ZHIPU_LEGACY_CN_RE = re.compile(
    r"\*\*(GLM-[0-9][\w.\-]*)\*\*[^\n]*?非高峰期\s*(\d+(?:\.\d+)?)\s*倍[，,]\s*"
    r"高峰期\s*(\d+(?:\.\d+)?)\s*倍"
)
# **GLM-5.4**: ... a rate of "0.67× during off-peak hours and 2× during peak hours".
_ZHIPU_LEGACY_EN_RE = re.compile(
    r"\*\*(GLM-[0-9][\w.\-]*)\*\*[^\n]*?(\d+(?:\.\d+)?)\s*[×x*]\s*during off-peak hours"
    r"\s+and\s+(\d+(?:\.\d+)?)\s*[×x*]\s*during peak"
)


def _parse_zhipu_legacy(text: str) -> _Parsed | None:
    """Parse the plan-revision notice (legacy V2 prompt multipliers)."""
    models: list[ModelMultiplier] = []
    seen: set[str] = set()
    for regex in (_ZHIPU_LEGACY_CN_RE, _ZHIPU_LEGACY_EN_RE):
        for m in regex.finditer(text):
            name = m.group(1).lower()
            if name in seen:
                continue
            seen.add(name)
            models.append(ModelMultiplier(
                model=name, peak=float(m.group(3)), off_peak=float(m.group(2)),
                peak_hours="14-18", off_peak_label="非高峰",
            ))
    if not models:
        return None

    peak_hours = _zhipu_peak_window(text) or "14-18"

    # | Lite 套餐 | 最多约 80 次 prompts | 最多约 400 次 prompts |
    # | Lite Plan | Up to approx. 80 prompts | Up to approx. 400 prompts |
    limits: dict[str, dict[str, float]] = {}
    for m in re.finditer(
        r"\|\s*(Lite|Pro|Max)(?:\s*(?:套餐|Plan))?\s*\|\s*"
        r"(?:最多约\s*|Up to approx\.?\s*)([\d,]+)\s*(?:次\s*)?prompts?\s*\|\s*"
        r"(?:最多约\s*|Up to approx\.?\s*)([\d,]+)",
        text,
        re.IGNORECASE,
    ):
        limits[m.group(1).lower()] = {
            "window_5h": float(m.group(2).replace(",", "")),
            "weekly": float(m.group(3).replace(",", "")),
        }

    parsed = _Parsed(mode="prompts", models=models, plan_limits=limits)
    parsed.note = _zhipu_prompt_note(peak_hours)
    return parsed


# <td>...mimo-v2.6-pro...</td><td>2.5 Credits</td><td>300 Credits</td><td>600 Credits</td>
_MIMO_MODEL_RE = re.compile(
    r"(mimo-[\w.\-]+)\s+([\d.]+)\s*Credits\s+([\d.]+)\s*Credits\s+([\d.]+)\s*Credits",
    re.IGNORECASE,
)


def _parse_xiaomi_plan(text: str) -> _Parsed | None:
    """Parse the MiMo Token Plan subscription page (Credit rates table)."""
    flat = _flatten(text)
    models = []
    for m in _MIMO_MODEL_RE.finditer(flat):
        models.append(ModelMultiplier(
            model=m.group(1).lower(),
            peak=1.0, off_peak=1.0, peak_hours="08-24", off_peak_label="夜间",
            # 表格列序：输入（命中缓存）/ 输入（未命中缓存）/ 输出
            cached_rate=float(m.group(2)), input_rate=float(m.group(3)),
            output_rate=float(m.group(4)), rate_unit="Credits/Token",
        ))
    if not models:
        return None

    # 夜间优惠速率：非高峰期（北京时间 0:00-8:00 …） 0.8x 消耗系数 /
    # a consumption coefficient of 0.8x applies
    off_peak = 0.8
    m = re.search(r"夜间[^\n]{0,120}?([\d.]+)\s*[x×]\s*消耗系数", text) or re.search(
        r"consumption coefficient of\s*([\d.]+)\s*[x×]", text, re.IGNORECASE
    )
    if m:
        off_peak = float(m.group(1))
    for model in models:
        model.off_peak = off_peak

    # 夜间窗口 00:00-08:00 → peak_hours "08-24"（卡片按补集展示夜间时段）
    peak_hours = "08-24"
    m = re.search(r"北京时间\s*(\d{1,2}):(\d{2})\s*[-–—~～]\s*(\d{1,2}):(\d{2})", flat) \
        or re.search(r"(\d{2}):(\d{2})\s*[–—-]\s*(\d{2}):(\d{2})\s*Beijing", flat, re.IGNORECASE)
    if m:
        start, end = int(m.group(1)), int(m.group(3))
        if start == 0 and 0 < end <= 24:
            peak_hours = f"{end:02d}-24"

    # 每月额度 | 41 亿 Credits | … / Monthly Quota | 4.1 billion Credits | …
    limits: dict[str, dict[str, float]] = {}
    quotas = _num_list(flat, "每月额度", r"亿", 4) or _num_list(
        flat, "Monthly Quota", r"billion\s*Credits", 4
    )
    if quotas:
        scale = 1e8 if "每月额度" in flat else 1e9
        for plan, value in zip(("lite", "standard", "pro", "max"), quotas):
            limits[plan] = {"monthly": round(value * scale)}

    # peak_hours "08-24" → 夜间窗口 "00-08"
    off_window = f"00-{peak_hours[:2]}" if peak_hours.endswith("-24") else ""
    note = f"输入/缓存/输出 = Credits/Token · 夜间（{off_window}）{off_peak:g}x"

    parsed = _Parsed(mode="credits", models=models, plan_limits=limits)
    parsed.note = note
    return parsed


_PARSERS: dict[str, Callable[[str], _Parsed | None]] = {
    "zhipu_overview": _parse_zhipu_overview,
    "zhipu_legacy": _parse_zhipu_legacy,
    "xiaomi_plan": _parse_xiaomi_plan,
}


@dataclass(frozen=True)
class _Source:
    url: str
    kind: str


_SOURCES: dict[str, tuple[_Source, ...]] = {
    "zhipu": (
        _Source("https://docs.bigmodel.cn/cn/coding-plan/overview.md", "zhipu_overview"),
        _Source("https://docs.z.ai/devpack/overview.md", "zhipu_overview"),
        _Source(
            "https://docs.bigmodel.cn/cn/coding-plan/notice/usage-revision.md",
            "zhipu_legacy",
        ),
        _Source("https://docs.z.ai/devpack/notice/usage-revision.md", "zhipu_legacy"),
    ),
    "xiaomi": (
        _Source(
            "https://mimo.mi.com/static/docs/tokenplan/Token%20Plan/subscription.md",
            "xiaomi_plan",
        ),
    ),
}


# ── State / persistence ─────────────────────────────────────────────


_sets: dict[str, MultiplierSet] = {}
_loaded = False
_refresh_task: asyncio.Task | None = None


def _persist_path():
    return paths.data_dir() / "model_multipliers.json"


def _load_persisted() -> dict[str, MultiplierSet]:
    try:
        data = json.loads(_persist_path().read_text(encoding="utf-8"))
        return {
            # 上次成功抓取的快照重启后即为缓存数据。
            key: replace(MultiplierSet.from_dict(d), source="cache")
            for key, d in (data.get("sets") or {}).items()
        }
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return {}


def _persist() -> None:
    try:
        path = _persist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"version": 1, "sets": {k: s.to_dict() for k, s in _sets.items()}},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Failed to persist multiplier cache: %s", e)


def _ensure_loaded() -> None:
    """Seed the in-memory cache: defaults first, then newer persisted fetches."""
    global _loaded
    if _loaded:
        return
    _sets.update(_default_sets())
    for key, persisted in _load_persisted().items():
        current = _sets.get(key)
        if current is None or _ts(persisted.fetched_at) > _ts(current.fetched_at):
            _sets[key] = persisted
    _loaded = True


def _reset_for_tests() -> None:
    """Drop in-memory state so tests can start from defaults each time."""
    global _loaded
    _sets.clear()
    _loaded = False


# ── Public read API (sync) ──────────────────────────────────────────


def get_set(provider: str, mode: str = "credits") -> MultiplierSet:
    """Best available set for a provider/mode ("live" → "cache" → defaults)."""
    _ensure_loaded()
    key = f"{provider}:{mode}"
    if key in _sets:
        return _sets[key]
    fallback = _sets.get(f"{provider}:credits")
    return fallback if fallback is not None else _default_sets()[key]


def get_plan_limits(provider: str, mode: str = "credits") -> dict[str, dict[str, float]]:
    return get_set(provider, mode).plan_limits


def snapshot_kwargs(provider: str, mode: str = "credits") -> dict[str, Any]:
    """Kwargs to merge into a :class:`QuotaSnapshot` for this provider/mode."""
    mset = get_set(provider, mode)
    return {
        "model_multipliers": list(mset.models),
        "multiplier_note": mset.note,
        "multiplier_source": mset.source,
        "multiplier_updated_at": mset.fetched_at,
    }


def get_all_sets() -> list[MultiplierSet]:
    _ensure_loaded()
    return [_sets[k] for k in sorted(_sets)]


# ── Fetch / refresh ─────────────────────────────────────────────────


async def _fetch_text(url: str) -> str | None:
    def _do() -> str:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ai-token-usage/1.0", "Accept": "text/markdown,text/plain,text/html,*/*"}
        )
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")

    try:
        return await asyncio.to_thread(_do)
    except Exception as exc:  # noqa: BLE001 — fetch failures never raise
        logger.info("Multiplier source fetch failed (%s): %s", url, exc)
        return None


async def refresh() -> dict[str, str]:
    """Fetch and parse every documentation source; update the cache.

    Returns ``{key: source_url}`` for the sets that were updated.  Never
    raises — on failure the previous (or default) data stays in place.
    """
    _ensure_loaded()
    updated: dict[str, str] = {}
    now = datetime.now(UTC).isoformat()

    for provider, sources in _SOURCES.items():
        for src in sources:
            text = await _fetch_text(src.url)
            if text is None:
                continue
            parser = _PARSERS[src.kind]
            try:
                parsed = parser(text)
            except Exception:
                logger.warning("Multiplier parse failed for %s", src.url, exc_info=True)
                continue
            if parsed is None or not parsed.models:
                logger.info("No multiplier data parsed from %s", src.url)
                continue

            # Pieces the page didn't mention keep the current values
            # (defaults on first load) instead of fabricating numbers.
            key = f"{provider}:{parsed.mode}"
            if key in updated:
                continue  # 本轮回补已成功 — 源列表中靠前的优先（中文站在前）
            base = _sets.get(key) or _default_sets()[key]
            models = parsed.models
            if parsed.plan_limits:
                limits = parsed.plan_limits
            else:
                limits = base.plan_limits
            _sets[key] = MultiplierSet(
                provider=provider,
                mode=parsed.mode,
                models=tuple(models),
                plan_limits=limits,
                note=parsed.note or base.note,
                source="live",
                fetched_at=now,
                source_url=src.url,
            )
            updated[key] = src.url

    if updated:
        _persist()
    return updated


# ── Background refresh loop ─────────────────────────────────────────


async def _refresh_loop() -> None:
    while True:
        try:
            await refresh()
        except Exception:
            logger.exception("Multiplier refresh failed")
        await asyncio.sleep(_REFRESH_INTERVAL_SECONDS)


def start_refresh_loop() -> bool:
    global _refresh_task
    if _refresh_task is not None and not _refresh_task.done():
        return False
    _refresh_task = asyncio.get_running_loop().create_task(_refresh_loop())
    return True


def stop_refresh_loop() -> None:
    global _refresh_task
    if _refresh_task is not None:
        _refresh_task.cancel()
        _refresh_task = None
