"""Tests for the model-multiplier registry and docs auto-refresh."""

import logging
from unittest.mock import patch

import pytest

from backend.quota import multipliers as mult_module
from backend.quota.base import ModelMultiplier
from backend.quota.xiaomi import XiaomiQuotaProvider, _token_rates
from backend.quota.zhipu import ZhipuQuotaProvider

# ── Fixtures: excerpts of the real documentation pages ──────────

# 2026-11-24 官网给 GLM-5.3-Flash 挂出限时半价：值用「~~旧~~ 新」删除线标记，
# 名称单元格内多了反斜杠换行。夹具保持官网原样（含行尾反斜杠，故用 raw 字符串）。
ZHIPU_OVERVIEW_CN = r"""
### 积分额度

| 套餐类型 | 5 小时积分 | 每周积分 |
| :-: | :-: | :-: |
| Lite 套餐 | 2,000 | 10,000 |
| Pro 套餐 | 12,000 | 60,000 |
| Max 套餐 | 28,000 | 140,000 |

<table>
  <tbody>
    <tr>
      <td rowSpan="3">模型</td>
      <td>GLM-5.4</td>
      <td>4.6</td>
      <td>1.1</td>
      <td>16</td>
    </tr>
    <tr>
      <td>GLM-5.3</td>
      <td>6.9</td>
      <td>1.7</td>
      <td>24</td>
    </tr>
    <tr>
      <td>GLM-5.3-Flash\
      （含视觉理解 MCP）</td>
      <td>~~2.3~~ 1.15</td>
      <td>~~0.56~~ 0.28</td>
      <td>~~8~~ 4</td>
    </tr>
    <tr>
      <td rowSpan="3">MCP 工具</td>
      <td>联网搜索</td>
      <td>—</td>
      <td>—</td>
      <td>1.2</td>
    </tr>
  </tbody>
</table>

**非高峰时段内，模型调用按基础积分消耗的 50% 抵扣。**

> [!NOTE]
>
> 高峰时段：每周一至周五的 14:00～18:00 （UTC+8）。

> **限时活动**：11 月 24 日至 12 月 24 日，调用 GLM-5.3-Flash 所产生的消耗全部按原抵扣系数的 50% 结算，即可用额度为原来的 2 倍。[查看 Flash 模型搭配使用指南](https://docs.bigmodel.cn/cn/coding-plan/learning-resources/flash-and-glm-5-4.md)。
"""

ZHIPU_OVERVIEW_EN = r"""
| Plan Type | 5-Hour Credits | Weekly Credits |
| :-: | :-: | :-: |
| Lite | 2,000 | 10,000 |
| Pro | 12,000 | 60,000 |
| Max | 28,000 | 140,000 |

<table>
  <tbody>
    <tr>
      <td rowSpan="3">Model</td>
      <td>GLM-5.4</td>
      <td>4.6</td>
      <td>1.1</td>
      <td>16</td>
    </tr>
    <tr>
      <td>GLM-5.3-Flash\
      (Including MCP for visual understanding)</td>
      <td>~~2.3~~ 1.15</td>
      <td>~~0.56~~ 0.28</td>
      <td>~~8~~ 4</td>
    </tr>
  </tbody>
</table>

**During off-peak hours, model usage is charged at 50% of the standard credit rate**.

> **Peak hours**: Monday to Friday, 14:00–18:00 Singapore Standard Time (UTC+8).

> **Limited-Time Offer:** From November 24 to December 24, all usage of GLM-5.3-Flash will be charged at 50% of the original quota consumption rate, effectively doubling your available quota.
"""

ZHIPU_LEGACY_CN = """
> **限时活动**：11 月 24 日至 12 月 24 日，调用 GLM-5.3-Flash 所产生的消耗全部按原抵扣系数的 50% 结算，即可用额度为原来的 2 倍。

> <li>
>   **GLM-5.4**：调用时将按照 “非高峰期 0.67 倍，高峰期 2 倍” 系数消耗额度。
> </li>
>
> <li>
>   **GLM-5.3**：调用时将按照 “非高峰期 1 倍，高峰期 3 倍” 系数消耗额度。
> </li>
>
> <li>
>   **GLM-5.3-Flash**：调用时将按照 “非高峰期 ~~0.4~~ 0.2 倍，高峰期 ~~1.2~~ 0.6 倍” 系数限时消耗额度。
> </li>
>
> 注：“高峰期”为**每周一至周五**的 14:00～18:00 （UTC+8）。

| 套餐类型 | 每 5 小时限额 | 每周限额 |
| :-: | :-: | :-: |
| Lite 套餐 | 最多约 80 次 prompts | 最多约 400 次 prompts |
| Pro 套餐 | 最多约 400 次 prompts | 最多约 2000 次 prompts |
| Max 套餐 | 最多约 1600 次 prompts | 最多约 8000 次 prompts |
"""

ZHIPU_LEGACY_EN = """
> **Limited-Time Offer:** From November 24 to December 24, all usage of GLM-5.3-Flash will be charged at 50% of the original quota consumption rate, effectively doubling your available quota.

>   **GLM-5.4**: As the flagship model, API calls consume quota at a rate of "0.67× during off-peak hours and 2× during peak hours".

>   **GLM-5.3-Flash**: API calls consume quota at a rate of ~~0.4×~~ 0.2× during off-peak hours and ~~1.2×~~ 0.6× during peak hours.

| Lite Plan | Up to approx. 80 prompts | Up to approx. 400 prompts |
| Pro Plan | Up to approx. 400 prompts | Up to approx. 2,000 prompts |
| Max Plan | Up to approx. 1,600 prompts | Up to approx. 8,000 prompts |

> Peak hours: Monday to Friday, 14:00–18:00 Singapore Standard Time (UTC+8).
"""

XIAOMI_PLAN_EN = """
<td><span style="display: inline-block; width: 100%; text-align: left;">**Monthly Quota**</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">4.1 billion Credits</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">11 billion Credits</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">38 billion Credits</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">82 billion Credits</span></td>

<table>
<tbody>
<tr>
<td><span style="display: inline-block; width: 100%; text-align: left;">mimo-v2.6-pro</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">2.5 Credits</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">300 Credits</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">600 Credits</span></td>
</tr>
<tr>
<td><span style="display: inline-block; width: 100%; text-align: left;">mimo-v2.6-flash</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">2 Credits</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">100 Credits</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">200 Credits</span></td>
</tr>
<tr>
<td><span style="display: inline-block; width: 100%; text-align: left;">mimo-v2.6-pro-ultraspeed</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">25 Credits</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">3000 Credits</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">6000 Credits</span></td>
</tr>
<tr>
<td><span style="display: inline-block; width: 100%; text-align: left;">mimo-v2.5-asr</span></td>
<td><span style="display: inline-block; width: 100%; text-align: left;">30M Credits</span></td>
</tr>
</tbody>
</table>

   - Off-peak discount rate: During non-peak hours (00:00–08:00 Beijing Time, equivalent to 16:00–24:00 UTC), a consumption coefficient of 0.8x applies.
"""

XIAOMI_PLAN_CN = """
| 每月额度 | 41 亿 Credits | 110 亿 Credits | 380 亿 Credits | 820 亿 Credits |

<table>
<tbody>
<tr>
<td>mimo-v2.6-pro</td>
<td>2.5 Credits</td>
<td>300 Credits</td>
<td>600 Credits</td>
</tr>
</tbody>
</table>

- 夜间优惠速率：非高峰期（北京时间 0:00-8:00，即 UTC 16:00-24:00） 0.8x 消耗系数。
"""


# ── Parser unit tests ───────────────────────────────────────────
# （注册表状态隔离由 conftest 的 _isolated_multiplier_cache 统一处理）


@pytest.mark.unit
def test_parse_zhipu_overview_cn():
    parsed = mult_module._parse_zhipu_overview(ZHIPU_OVERVIEW_CN)
    assert parsed is not None and parsed.mode == "credits"
    names = {m.model for m in parsed.models}
    assert names == {"glm-5.4", "glm-5.3", "glm-5.3-flash"}  # MCP 工具行不进模型表
    # 限时半价行：删除线旧值 2.3/0.56/8 必须被忽略，取新值
    flash = next(m for m in parsed.models if m.model == "glm-5.3-flash")
    assert flash.input_rate == 1.15 and flash.cached_rate == 0.28 and flash.output_rate == 4.0
    assert flash.tag == "限时"
    assert all(m.off_peak == 0.5 for m in parsed.models)      # 非高峰 5 折
    assert all(m.tag == "" for m in parsed.models if m.model != "glm-5.3-flash")
    assert parsed.plan_limits["lite"]["window_5h"] == 2000
    assert parsed.plan_limits["max"]["weekly"] == 140000
    assert "14-18" in parsed.note
    assert "glm-5.3-flash 限时活动（11-24~12-24）" in parsed.note


@pytest.mark.unit
def test_parse_zhipu_overview_en():
    parsed = mult_module._parse_zhipu_overview(ZHIPU_OVERVIEW_EN)
    assert parsed is not None
    by_name = {m.model: m for m in parsed.models}
    assert set(by_name) == {"glm-5.4", "glm-5.3-flash"}
    assert by_name["glm-5.3-flash"].input_rate == 1.15
    assert by_name["glm-5.3-flash"].tag == "限时"
    assert parsed.plan_limits["pro"]["weekly"] == 60000
    assert "限时活动（11-24~12-24）" in parsed.note       # 英文月份 → 数字区间


@pytest.mark.unit
def test_parse_zhipu_legacy():
    parsed = mult_module._parse_zhipu_legacy(ZHIPU_LEGACY_CN)
    assert parsed is not None and parsed.mode == "prompts"
    by_name = {m.model: m for m in parsed.models}
    assert by_name["glm-5.4"].peak == 2.0 and by_name["glm-5.4"].off_peak == 0.67
    assert by_name["glm-5.3"].peak == 3.0 and by_name["glm-5.3"].off_peak == 1.0
    # 限时行：“非高峰期 ~~0.4~~ 0.2 倍，高峰期 ~~1.2~~ 0.6 倍”
    flash = by_name["glm-5.3-flash"]
    assert flash.peak == 0.6 and flash.off_peak == 0.2 and flash.tag == "限时"
    assert by_name["glm-5.4"].tag == ""
    assert parsed.plan_limits["lite"]["window_5h"] == 80
    assert parsed.plan_limits["pro"]["weekly"] == 2000


@pytest.mark.unit
def test_parse_zhipu_legacy_en():
    parsed = mult_module._parse_zhipu_legacy(ZHIPU_LEGACY_EN)
    assert parsed is not None
    by_name = {m.model: m for m in parsed.models}
    assert by_name["glm-5.4"].off_peak == 0.67 and by_name["glm-5.4"].peak == 2.0
    # "~~0.4×~~ 0.2× during off-peak hours and ~~1.2×~~ 0.6× during peak hours"
    assert by_name["glm-5.3-flash"].peak == 0.6 and by_name["glm-5.3-flash"].off_peak == 0.2
    assert by_name["glm-5.3-flash"].tag == "限时"
    assert parsed.plan_limits["pro"]["window_5h"] == 400


@pytest.mark.unit
def test_parse_xiaomi_plan_en():
    parsed = mult_module._parse_xiaomi_plan(XIAOMI_PLAN_EN)
    assert parsed is not None
    by_name = {m.model: m for m in parsed.models}
    # ASR 行只有单列时长，不应进模型倍率表
    assert set(by_name) == {"mimo-v2.6-pro", "mimo-v2.6-flash", "mimo-v2.6-pro-ultraspeed"}
    pro = by_name["mimo-v2.6-pro"]
    assert pro.input_rate == 300.0 and pro.cached_rate == 2.5 and pro.output_rate == 600.0
    assert pro.off_peak == 0.8 and pro.peak_hours == "08-24"
    assert parsed.plan_limits["lite"]["monthly"] == pytest.approx(4.1e9)
    assert parsed.plan_limits["max"]["monthly"] == pytest.approx(82e9)
    assert "00-08" in parsed.note


@pytest.mark.unit
def test_parse_xiaomi_plan_cn():
    parsed = mult_module._parse_xiaomi_plan(XIAOMI_PLAN_CN)
    assert parsed is not None
    assert parsed.models[0].input_rate == 300.0
    assert parsed.models[0].off_peak == 0.8
    assert parsed.plan_limits["lite"]["monthly"] == pytest.approx(4.1e9)
    assert parsed.plan_limits["pro"]["monthly"] == pytest.approx(38e9)


@pytest.mark.unit
def test_parse_garbage_returns_none():
    assert mult_module._parse_zhipu_overview("nothing here") is None
    assert mult_module._parse_zhipu_legacy("nothing here") is None
    assert mult_module._parse_xiaomi_plan("nothing here") is None


@pytest.mark.unit
def test_parsed_window_reaches_models():
    """官方调整时段时，模型字段必须跟着变——历史 V2 角标直接渲染 peak_hours，
    只更新说明文字会让角标与说明不一致。"""
    overview = ZHIPU_OVERVIEW_CN.replace("14:00～18:00", "15:00～19:00")
    parsed = mult_module._parse_zhipu_overview(overview)
    assert parsed is not None
    assert {m.peak_hours for m in parsed.models} == {"15-19"}

    legacy = ZHIPU_LEGACY_CN.replace("14:00～18:00", "15:00～19:00")
    parsed = mult_module._parse_zhipu_legacy(legacy)
    assert parsed is not None
    assert {m.peak_hours for m in parsed.models} == {"15-19"}

    mimo = XIAOMI_PLAN_EN.replace("00:00–08:00", "00:00–06:00")
    parsed = mult_module._parse_xiaomi_plan(mimo)
    assert parsed is not None
    assert {m.peak_hours for m in parsed.models} == {"06-24"}
    assert "00-06" in parsed.note
    assert {m.off_peak for m in parsed.models} == {0.8}


@pytest.mark.unit
def test_normalize_handles_html_and_footnote_revisions():
    """调价标记换成 HTML / 脚注写法时同样要能解析（否则整行模型被静默丢弃）。"""
    page = (
        "<table><tbody>\n"
        "<tr><td>GLM-5.4[^1]</td>"
        "<td><del>4.6</del> <strong>2.3</strong></td><td>1.1</td><td>16</td></tr>\n"
        "</tbody></table>"
    )
    parsed = mult_module._parse_zhipu_overview(page)
    assert parsed is not None
    assert [m.model for m in parsed.models] == ["glm-5.4"]
    assert parsed.models[0].input_rate == 2.3
    assert parsed.models[0].cached_rate == 1.1


@pytest.mark.asyncio
async def test_refresh_warns_when_a_model_disappears(caplog):
    """模型可能被官方名正言顺地下线/改名（如 mimo-v2.5 → v2.6），所以更新照常
    生效；但行解析失败看起来一模一样，因此必须留下告警便于排查。"""

    async def fake_fetch(url: str) -> str | None:
        # 模拟官网改版后 Flash 行无法识别（名称不再是 GLM-数字 开头）
        if "overview.md" not in url:
            return None
        return ZHIPU_OVERVIEW_CN.replace("GLM-5.3-Flash", "GLM-X")

    with (
        caplog.at_level(logging.WARNING, logger="backend.quota.multipliers"),
        patch.object(mult_module, "_fetch_text", fake_fetch),
    ):
        await mult_module.refresh()
    assert "glm-5.3-flash" in caplog.text
    assert "no longer yields" in caplog.text
    zhipu = mult_module.get_set("zhipu", "credits")
    assert {m.model for m in zhipu.models} == {"glm-5.4", "glm-5.3"}


# ── Defaults & read API ─────────────────────────────────────────


@pytest.mark.unit
def test_defaults_cover_all_provider_modes():
    zhipu = mult_module.get_set("zhipu", "credits")
    assert zhipu.source == "defaults"
    assert {m.model for m in zhipu.models} == {"glm-5.4", "glm-5.3", "glm-5.3-flash"}
    # 内置快照与 2026-11-25 官网一致：Flash 限时半价
    flash = next(m for m in zhipu.models if m.model == "glm-5.3-flash")
    assert (flash.input_rate, flash.cached_rate, flash.output_rate) == (1.15, 0.28, 4.0)
    assert flash.tag == "限时"
    prompts = mult_module.get_set("zhipu", "prompts")
    assert all(m.input_rate is None for m in prompts.models)
    legacy_flash = next(m for m in prompts.models if m.model == "glm-5.3-flash")
    assert (legacy_flash.peak, legacy_flash.off_peak) == (0.6, 0.2)
    xiaomi = mult_module.get_set("xiaomi", "credits")
    assert {m.model for m in xiaomi.models} == {
        "mimo-v2.6-pro", "mimo-v2.6-flash", "mimo-v2.6-pro-ultraspeed",
    }


@pytest.mark.unit
def test_model_multiplier_roundtrip():
    m = ModelMultiplier(
        model="glm-5.4", peak=2.0, off_peak=0.67, peak_hours="14-18",
        off_peak_label="非高峰", input_rate=4.6, cached_rate=1.1,
        output_rate=16.0, rate_unit="积分/万Token", tag="限时",
    )
    assert ModelMultiplier.from_dict(m.to_dict()) == m


# ── Refresh / persistence ───────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_merges_parsed_sets():
    async def fake_fetch(url: str) -> str | None:
        if url.endswith("overview.md") and "bigmodel" in url:
            return ZHIPU_OVERVIEW_CN
        if "mimo.mi.com" in url:
            return XIAOMI_PLAN_EN
        return None

    with patch.object(mult_module, "_fetch_text", fake_fetch):
        updated = await mult_module.refresh()

    assert "zhipu:credits" in updated and "xiaomi:credits" in updated
    zhipu = mult_module.get_set("zhipu", "credits")
    assert zhipu.source == "live"
    assert zhipu.fetched_at != ""
    # 未返回的 legacy 源保持内置默认
    assert mult_module.get_set("zhipu", "prompts").source == "defaults"


@pytest.mark.asyncio
async def test_refresh_failure_keeps_previous_data():
    async def fetch_none(url: str) -> str | None:
        return None

    with patch.object(mult_module, "_fetch_text", fetch_none):
        updated = await mult_module.refresh()
    assert updated == {}
    assert mult_module.get_set("zhipu", "credits").source == "defaults"


@pytest.mark.asyncio
async def test_persist_and_reload(tmp_path):
    async def fake_fetch(url: str) -> str | None:
        return XIAOMI_PLAN_EN if "mimo.mi.com" in url else None

    with patch.object(mult_module, "_fetch_text", fake_fetch):
        await mult_module.refresh()
    assert (tmp_path / "model_multipliers.json").exists()

    # 模拟重启：内存清空后从持久化文件恢复（标记为 cache 来源）
    mult_module._reset_for_tests()
    xiaomi = mult_module.get_set("xiaomi", "credits")
    assert xiaomi.source == "cache"
    assert {m.model for m in xiaomi.models} == {
        "mimo-v2.6-pro", "mimo-v2.6-flash", "mimo-v2.6-pro-ultraspeed",
    }


# ── Provider integration ────────────────────────────────────────


@pytest.mark.unit
def test_zhipu_mode_from_response_type():
    p = ZhipuQuotaProvider({"enabled": True, "plan_type": "pro"})
    assert p.mode == "credits"                      # 未识别前默认积分制
    p._parse_coding_plan_response({
        "success": True,
        "data": {"level": "PRO",
                 "limits": [{"type": "TOKENS_LIMIT", "unit": 3, "percentage": 10.0}]},
    })
    assert p.mode == "prompts"                      # TOKENS_LIMIT → 历史 V2
    assert all(m.input_rate is None for m in p.multipliers)
    p._parse_coding_plan_response({
        "success": True,
        "data": {"level": "PRO",
                 "limits": [{"type": "CREDIT_LIMIT", "unit": 3, "percentage": 10.0}]},
    })
    assert p.mode == "credits"
    assert any(m.input_rate is not None for m in p.multipliers)


@pytest.mark.unit
def test_zhipu_mode_config_override():
    p = ZhipuQuotaProvider({"enabled": True, "plan_mode": "prompts"})
    assert p.mode == "prompts"
    p2 = ZhipuQuotaProvider({"enabled": True, "plan_mode": "credits"})
    assert p2.mode == "credits"


@pytest.mark.unit
def test_snapshot_kwargs_fields():
    kwargs = mult_module.snapshot_kwargs("zhipu", "credits")
    assert kwargs["multiplier_source"] == "defaults"
    assert kwargs["multiplier_note"]
    assert kwargs["multiplier_updated_at"] == mult_module._DEFAULTS_AS_OF
    assert kwargs["model_multipliers"][0].model == "glm-5.4"


@pytest.mark.unit
def test_xiaomi_token_rates_and_aliases():
    rates = _token_rates()
    assert rates[("mimo-v2.6-pro", "input_miss")] == 300.0
    assert rates[("mimo-v2.6-flash", "output")] == 200.0
    # 已下线的旧模型名映射到现行倍率（历史 token_usage 估算用）
    assert rates[("mimo-v2.5-pro", "input_miss")] == 300.0
    assert rates[("mimo-v2.5", "output")] == 200.0
    p = XiaomiQuotaProvider({"enabled": True})
    assert any(m.model == "mimo-v2.6-pro" for m in p.multipliers)
