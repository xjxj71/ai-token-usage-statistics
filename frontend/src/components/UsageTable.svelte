<script lang="ts">
  import type { TokenRecord } from "../types";

  interface Props {
    items: TokenRecord[];
    total: number;
    page: number;
    pageSize: number;
    onPageChange: (page: number) => void;
    onExport?: () => void;
  }

  let { items, total, page, pageSize, onPageChange, onExport }: Props = $props();

  let searchQuery = $state("");

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

  let filteredItems = $derived(
    searchQuery
      ? items.filter(
          (i) =>
            i.agent.toLowerCase().includes(searchQuery.toLowerCase()) ||
            i.model.toLowerCase().includes(searchQuery.toLowerCase())
        )
      : items
  );

  let totalPages = $derived(Math.max(1, Math.ceil(total / pageSize)));
  let jumpPage = $state("");

  const agentColors: Record<string, { bg: string; text: string }> = {
    hermes: { bg: "rgba(99,102,241,.2)", text: "#818CF8" },
    "claude-code": { bg: "rgba(139,92,246,.2)", text: "#A78BFA" },
    openclaw: { bg: "rgba(16,185,129,.2)", text: "#34D399" },
    openclaude: { bg: "rgba(245,158,11,.2)", text: "#FBBF24" },
    hanako: { bg: "rgba(236,72,153,.2)", text: "#F472B6" },
  };

  function getAgentColor(agent: string) {
    return agentColors[agent] || { bg: "rgba(99,102,241,.2)", text: "#818CF8" };
  }

  function pageNumbers(): number[] {
    const pages: number[] = [];
    const start = Math.max(1, page - 2);
    const end = Math.min(totalPages, page + 2);
    for (let i = start; i <= end; i++) pages.push(i);
    return pages;
  }

  function handleJump() {
    const p = parseInt(jumpPage, 10);
    if (!isNaN(p) && p >= 1 && p <= totalPages) {
      onPageChange(p);
      jumpPage = "";
    }
  }

  function handleJumpKeydown(e: KeyboardEvent) {
    if (e.key === "Enter") handleJump();
  }
</script>

<div class="table-card">
  <div class="table-header">
    <h3 class="chart-title">使用记录</h3>
    <div class="flex items-center gap-3">
      <span class="text-xs text-[var(--text-3)]">共 {total} 条</span>
      <div class="search-box">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
        <input
          type="text"
          placeholder="搜索 Agent / 模型..."
          bind:value={searchQuery}
          class="search-input"
        />
      </div>
      {#if onExport}
        <button class="export-btn" onclick={onExport}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
          导出 CSV
        </button>
      {/if}
    </div>
  </div>

  <div class="overflow-x-auto">
    <table>
      <thead>
        <tr>
          <th>时间</th>
          <th>Agent</th>
          <th>模型</th>
          <th class="text-right">输入</th>
          <th class="text-right">输出</th>
          <th class="text-right">缓存</th>
          <th class="text-right">费用</th>
        </tr>
      </thead>
      <tbody>
        {#each filteredItems as item}
          {@const c = getAgentColor(item.agent)}
          <tr>
            <td class="text-[var(--text-2)]">{fmtTime(item.timestamp)}</td>
            <td>
              <span class="agent-badge" style="background:{c.bg};color:{c.text}">
                {item.agent}
              </span>
            </td>
            <td class="text-[var(--text-2)]">{item.model}</td>
            <td class="text-right text-[var(--text-2)]">{fmt(item.input_tokens)}</td>
            <td class="text-right text-[var(--text-2)]">{fmt(item.output_tokens)}</td>
            <td class="text-right text-[var(--text-2)]">
              {fmt(item.cache_read_tokens + item.cache_write_tokens)}
            </td>
            <td class="text-right text-[var(--amber)]">${item.cost_usd.toFixed(4)}</td>
          </tr>
        {:else}
          <tr>
            <td colspan="7" class="empty-row">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
              <span>暂无使用记录</span>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  {#if totalPages > 1}
    <div class="pagination">
      <span class="text-xs text-[var(--text-3)]">
        第 {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} 条 / 共 {total} 条
      </span>
      <div class="flex items-center gap-1">
        <button class="page-btn" disabled={page <= 1} onclick={() => onPageChange(1)} title="首页">&laquo;</button>
        <button class="page-btn" disabled={page <= 1} onclick={() => onPageChange(page - 1)}>&lsaquo;</button>
        {#each pageNumbers() as p}
          <button class="page-btn {p === page ? 'active' : ''}" onclick={() => onPageChange(p)}>
            {p}
          </button>
        {/each}
        <button class="page-btn" disabled={page >= totalPages} onclick={() => onPageChange(page + 1)}>&rsaquo;</button>
        <button class="page-btn" disabled={page >= totalPages} onclick={() => onPageChange(totalPages)} title="末页">&raquo;</button>
        <span class="text-xs text-[var(--text-3)] ml-2">跳至</span>
        <input
          type="number"
          bind:value={jumpPage}
          onkeydown={handleJumpKeydown}
          min="1"
          max={totalPages}
          class="jump-input"
          placeholder=""
        />
        <button class="page-btn" onclick={handleJump}>Go</button>
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
  .search-box {
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 6px 12px;
  }
  .search-box:focus-within {
    border-color: var(--primary);
  }
  .search-input {
    background: transparent;
    border: none;
    outline: none;
    color: var(--text);
    font-size: 13px;
    width: 180px;
  }
  .search-input::placeholder {
    color: var(--text-3);
  }
  .export-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 7px 14px;
    border-radius: 8px;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-2);
  }
  .export-btn:hover {
    border-color: var(--primary);
    color: var(--text);
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  th {
    text-align: left;
    padding: 10px 16px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-3);
    border-bottom: 1px solid var(--border);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  td {
    padding: 10px 16px;
    font-size: 13px;
    border-bottom: 1px solid rgba(51, 65, 85, 0.4);
  }
  tr:hover td {
    background: rgba(99, 102, 241, 0.06);
  }
  .agent-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 9999px;
    font-size: 11px;
    font-weight: 600;
  }
  .empty-row {
    text-align: center;
    padding: 32px 16px;
    color: var(--text-3);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
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
  .jump-input {
    width: 48px;
    padding: 4px 8px;
    font-size: 13px;
    text-align: center;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    outline: none;
  }
  .jump-input:focus {
    border-color: var(--primary);
  }
</style>
