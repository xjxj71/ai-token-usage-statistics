<script lang="ts">
  import type { SessionItem, TokenRecord } from "../types";

  interface Props {
    items: SessionItem[];
    total: number;
    page: number;
    pageSize: number;
    usdToCnyRate?: number;
    loadDetail: (agent: string, sessionId: string) => Promise<TokenRecord[]>;
    onPageChange: (page: number) => void;
    onPageSizeChange?: (size: number) => void;
  }

  let {
    items,
    total,
    page,
    pageSize,
    usdToCnyRate = 7.25,
    loadDetail,
    onPageChange,
    onPageSizeChange,
  }: Props = $props();

  const PAGE_SIZES = [10, 20, 50];
  const DETAIL_LIMIT = 200;

  let expandedKey: string | null = $state(null);
  let loadingKey: string | null = $state(null);
  let details: Record<string, TokenRecord[]> = $state({});

  function sessionKey(s: SessionItem): string {
    return `${s.agent}|${s.session_id}`;
  }

  function fmt(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    return n.toLocaleString();
  }

  function fmtTime(ts: string): string {
    try {
      return new Date(ts).toLocaleString();
    } catch {
      return ts;
    }
  }

  function totalTokens(s: SessionItem): number {
    return s.input_tokens + s.output_tokens + s.cache_read_tokens + s.cache_write_tokens;
  }

  async function toggleExpand(s: SessionItem) {
    const key = sessionKey(s);
    if (expandedKey === key) {
      expandedKey = null;
      return;
    }
    expandedKey = key;
    if (!details[key]) {
      loadingKey = key;
      try {
        details[key] = await loadDetail(s.agent, s.session_id);
      } catch {
        details[key] = [];
      } finally {
        loadingKey = null;
      }
    }
  }

  let totalPages = $derived(Math.max(1, Math.ceil(total / pageSize)));

  function pageNumbers(): number[] {
    const pages: number[] = [];
    const start = Math.max(1, page - 2);
    const end = Math.min(totalPages, page + 2);
    for (let i = start; i <= end; i++) pages.push(i);
    return pages;
  }

  const agentColors: Record<string, { bg: string; text: string }> = {
    hermes: { bg: "rgba(99,102,241,.2)", text: "#818CF8" },
    "hermes-win": { bg: "rgba(129,140,248,.2)", text: "#A5B4FC" },
    "claude-code": { bg: "rgba(139,92,246,.2)", text: "#A78BFA" },
    openclaw: { bg: "rgba(16,185,129,.2)", text: "#34D399" },
    hanako: { bg: "rgba(236,72,153,.2)", text: "#F472B6" },
    openclaude: { bg: "rgba(245,158,11,.2)", text: "#FBBF24" },
    "mimo-code": { bg: "rgba(14,165,233,.2)", text: "#38BDF8" },
    opencode: { bg: "rgba(20,184,166,.2)", text: "#2DD4BF" },
    zcode: { bg: "rgba(249,115,22,.2)", text: "#FB923C" },
  };

  function getAgentColor(agent: string) {
    return agentColors[agent] || { bg: "rgba(99,102,241,.2)", text: "#818CF8" };
  }
</script>

<div class="table-card">
  <div class="table-header">
    <h3 class="chart-title">会话明细</h3>
    <div class="flex items-center gap-3">
      <span class="text-xs text-[var(--text-3)]">共 {total} 个会话 · 点击行展开请求明细</span>
      {#if onPageSizeChange}
        <div class="page-size-group">
          {#each PAGE_SIZES as size}
            <button class="size-btn {pageSize === size ? 'active' : ''}" onclick={() => onPageSizeChange(size)}>{size}</button>
          {/each}
        </div>
      {/if}
    </div>
  </div>

  <div class="overflow-x-auto">
    <table>
      <thead>
        <tr>
          <th class="w-8"></th>
          <th>最近活动</th>
          <th>Agent</th>
          <th>项目</th>
          <th>模型</th>
          <th class="text-right">请求数</th>
          <th class="text-right">Token</th>
          <th class="text-right">思考</th>
          <th class="text-right">费用</th>
        </tr>
      </thead>
      <tbody>
        {#each items as s (sessionKey(s))}
          {@const key = sessionKey(s)}
          {@const c = getAgentColor(s.agent)}
          <tr class="session-row {expandedKey === key ? 'expanded' : ''}" onclick={() => toggleExpand(s)}>
            <td>
              <svg
                class="chevron {expandedKey === key ? 'open' : ''}"
                width="14" height="14" viewBox="0 0 24 24" fill="none"
                stroke="var(--text-3)" stroke-width="2"
              ><path d="M9 18l6-6-6-6"/></svg>
            </td>
            <td class="text-[var(--text-2)] whitespace-nowrap">{fmtTime(s.last_ts)}</td>
            <td>
              <span class="agent-badge" style="background:{c.bg};color:{c.text}">{s.agent}</span>
            </td>
            <td class="text-[var(--text-2)]">{s.project || "—"}</td>
            <td class="text-[var(--text-2)] truncate max-w-[200px]" title={s.models.join(", ")}>
              {s.models.join(", ") || "—"}
            </td>
            <td class="text-right text-[var(--text-2)]">{s.call_count}</td>
            <td class="text-right text-[var(--text-2)]">{fmt(totalTokens(s))}</td>
            <td class="text-right text-[var(--text-2)]">{fmt(s.reasoning_tokens)}</td>
            <td class="text-right text-[var(--amber)]">¥{(s.cost_usd * usdToCnyRate).toFixed(2)}</td>
          </tr>
          {#if expandedKey === key}
            <tr class="detail-row">
              <td></td>
              <td colspan="8">
                {#if loadingKey === key}
                  <div class="detail-loading">加载请求明细...</div>
                {:else if (details[key] ?? []).length === 0}
                  <div class="detail-loading">该会话暂无明细记录</div>
                {:else}
                  <table class="detail-table">
                    <thead>
                      <tr>
                        <th>时间</th>
                        <th>模型</th>
                        <th class="text-right">输入</th>
                        <th class="text-right">输出</th>
                        <th class="text-right">思考</th>
                        <th class="text-right">缓存</th>
                        <th class="text-right">费用</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each details[key] as r (r.id)}
                        <tr>
                          <td class="whitespace-nowrap">{fmtTime(r.timestamp)}</td>
                          <td class="truncate max-w-[220px]" title={r.model}>{r.model}</td>
                          <td class="text-right">{fmt(r.input_tokens)}</td>
                          <td class="text-right">{fmt(r.output_tokens)}</td>
                          <td class="text-right">{fmt(r.reasoning_tokens ?? 0)}</td>
                          <td class="text-right">{fmt(r.cache_read_tokens + r.cache_write_tokens)}</td>
                          <td class="text-right text-[var(--amber)]">¥{(r.cost_usd * usdToCnyRate).toFixed(3)}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                  {#if (details[key] ?? []).length >= DETAIL_LIMIT}
                    <div class="detail-loading">仅显示最近 {DETAIL_LIMIT} 条请求</div>
                  {/if}
                {/if}
              </td>
            </tr>
          {/if}
        {:else}
          <tr>
            <td colspan="9" class="empty-row">
              <span>当前范围内没有会话记录</span>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  {#if totalPages > 1}
    <div class="pagination">
      <span class="text-xs text-[var(--text-3)]">
        第 {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} 个 / 共 {total} 个
      </span>
      <div class="flex items-center gap-1">
        <button class="page-btn" disabled={page <= 1} onclick={() => onPageChange(1)} title="首页">&laquo;</button>
        <button class="page-btn" disabled={page <= 1} onclick={() => onPageChange(page - 1)}>&lsaquo;</button>
        {#each pageNumbers() as p}
          <button class="page-btn {p === page ? 'active' : ''}" onclick={() => onPageChange(p)}>{p}</button>
        {/each}
        <button class="page-btn" disabled={page >= totalPages} onclick={() => onPageChange(page + 1)}>&rsaquo;</button>
        <button class="page-btn" disabled={page >= totalPages} onclick={() => onPageChange(totalPages)} title="末页">&raquo;</button>
      </div>
    </div>
  {/if}
</div>

<style>
  .table-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }
  .table-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
  }
  .chart-title {
    font-size: 14px;
    font-weight: 600;
  }
  .page-size-group {
    display: flex;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }
  .size-btn {
    padding: 3px 10px;
    font-size: 12px;
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    transition: all 0.15s;
    border-right: 1px solid var(--border);
  }
  .size-btn:last-child {
    border-right: none;
  }
  .size-btn.active {
    background: var(--primary);
    color: #fff;
  }
  .size-btn:hover:not(.active) {
    background: rgba(99, 102, 241, 0.08);
    color: var(--text);
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  th {
    padding: 10px 16px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-3);
    border-bottom: 1px solid var(--border);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  th.text-right {
    text-align: right;
  }
  th:not(.text-right) {
    text-align: left;
  }
  td {
    padding: 10px 16px;
    font-size: 13px;
    border-bottom: 1px solid rgba(51, 65, 85, 0.4);
  }
  .session-row {
    cursor: pointer;
  }
  .session-row:hover td {
    background: rgba(99, 102, 241, 0.06);
  }
  .session-row.expanded td {
    background: rgba(99, 102, 241, 0.08);
  }
  .chevron {
    transition: transform 0.15s;
  }
  .chevron.open {
    transform: rotate(90deg);
  }
  .agent-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 9999px;
    font-size: 11px;
    font-weight: 600;
  }
  .detail-row td {
    background: rgba(15, 23, 42, 0.5);
    border-bottom: 1px solid var(--border);
  }
  .detail-table {
    width: 100%;
  }
  .detail-table th {
    padding: 6px 12px;
    font-size: 11px;
  }
  .detail-table td {
    padding: 5px 12px;
    font-size: 12px;
    color: var(--text-2);
    border-bottom: 1px solid rgba(51, 65, 85, 0.25);
  }
  .detail-loading {
    padding: 12px;
    font-size: 12px;
    color: var(--text-3);
  }
  .empty-row {
    text-align: center;
    padding: 32px 16px;
    color: var(--text-3);
  }
  .pagination {
    padding: 12px 20px;
    border-top: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
  }
  .page-btn {
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-2);
  }
  .page-btn:hover:not(:disabled) {
    border-color: var(--primary);
    color: var(--text);
  }
  .page-btn.active {
    background: var(--primary);
    border-color: var(--primary);
    color: #fff;
  }
  .page-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }
</style>
