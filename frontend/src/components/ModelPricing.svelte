<script lang="ts">
  import { onMount } from "svelte";

  interface PricingItem {
    model: string;
    input_price: number;
    output_price: number;
    cache_read_price: number;
    cache_write_price: number;
  }

  const BASE = "/api";
  const USD_TO_CNY = 7.25;
  const PAGE_SIZES = [10, 20, 50];

  let pricingData: PricingItem[] = $state([]);
  let loading = $state(true);
  let saving = $state<string | null>(null);
  let editingModel: string | null = $state(null);
  let editForm = $state({ input_price: 0, output_price: 0, cache_read_price: 0, cache_write_price: 0 });
  let saveMsg = $state<{ model: string; ok: boolean; text: string } | null>(null);
  let expanded = $state(false);
  let refreshing = $state(false);
  let refreshMsg = $state<{ ok: boolean; text: string } | null>(null);

  // 分页状态
  let pageSize = $state(20);
  let currentPage = $state(1);
  let searchQuery = $state("");

  let filteredData = $derived(
    searchQuery
      ? pricingData.filter((p) => p.model.toLowerCase().includes(searchQuery.toLowerCase()))
      : pricingData
  );
  let totalPages = $derived(Math.max(1, Math.ceil(filteredData.length / pageSize)));
  let pagedData = $derived(filteredData.slice((currentPage - 1) * pageSize, currentPage * pageSize));

  function changePageSize(size: number) {
    pageSize = size;
    currentPage = 1;
  }

  function goToPage(p: number) {
    if (p >= 1 && p <= totalPages) currentPage = p;
  }

  function pageNumbers(): number[] {
    const pages: number[] = [];
    const start = Math.max(1, currentPage - 2);
    const end = Math.min(totalPages, currentPage + 2);
    for (let i = start; i <= end; i++) pages.push(i);
    return pages;
  }

  async function loadPricing() {
    loading = true;
    try {
      const res = await fetch(`${BASE}/pricing`);
      if (!res.ok) throw new Error("获取定价失败");
      pricingData = await res.json();
    } catch (e: any) {
      console.error("加载定价失败:", e);
    } finally {
      loading = false;
    }
  }

  function startEdit(item: PricingItem) {
    editingModel = item.model;
    editForm = {
      input_price: +(item.input_price * USD_TO_CNY).toFixed(2),
      output_price: +(item.output_price * USD_TO_CNY).toFixed(2),
      cache_read_price: +(item.cache_read_price * USD_TO_CNY).toFixed(2),
      cache_write_price: +(item.cache_write_price * USD_TO_CNY).toFixed(2),
    };
    saveMsg = null;
  }

  function cancelEdit() {
    editingModel = null;
    saveMsg = null;
  }

  async function saveEdit(model: string) {
    saving = model;
    saveMsg = null;
    try {
      const encoded = encodeURIComponent(model);
      const usdForm = {
        input_price: +(editForm.input_price / USD_TO_CNY).toFixed(6),
        output_price: +(editForm.output_price / USD_TO_CNY).toFixed(6),
        cache_read_price: +(editForm.cache_read_price / USD_TO_CNY).toFixed(6),
        cache_write_price: +(editForm.cache_write_price / USD_TO_CNY).toFixed(6),
      };
      const res = await fetch(`${BASE}/pricing/${encoded}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(usdForm),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "保存失败");
      }
      pricingData = pricingData.map((p) =>
        p.model === model ? { ...p, ...usdForm } : p
      );
      saveMsg = { model, ok: true, text: "已保存" };
      editingModel = null;
    } catch (e: any) {
      saveMsg = { model, ok: false, text: e.message || "保存失败" };
    } finally {
      saving = null;
    }
  }

  async function refreshPricing() {
    refreshing = true;
    refreshMsg = null;
    try {
      const res = await fetch(`${BASE}/pricing/refresh`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "更新失败");
      }
      const data = await res.json();
      refreshMsg = { ok: true, text: `已更新 ${data.updated || 0} 个模型的定价` };
      await loadPricing();
    } catch (e: any) {
      refreshMsg = { ok: false, text: e.message || "更新失败" };
    } finally {
      refreshing = false;
    }
  }

  function toggleExpand() {
    expanded = !expanded;
  }

  function toCNY(usd: number): string {
    return (usd * USD_TO_CNY).toFixed(2);
  }

  onMount(() => {
    loadPricing();
  });
</script>

<div class="pricing-card">
  <button class="pricing-header" onclick={toggleExpand}>
    <h3 class="chart-title">模型定价管理</h3>
    <div class="flex items-center gap-2">
      <span class="text-xs text-[var(--text-3)]">共 {pricingData.length} 个模型</span>
      <svg class="chevron {expanded ? 'open' : ''}" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
    </div>
  </button>

  {#if expanded}
    <div class="pricing-body">
      {#if loading}
        <div class="text-center text-[var(--text-3)] py-8">加载中...</div>
      {:else}
        <div class="toolbar">
          <button class="refresh-btn" onclick={refreshPricing} disabled={refreshing}>
            <svg class="spin-icon {refreshing ? 'spinning' : ''}" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 2v6h-6M3 12a9 9 0 0 1 15-6.7L21 8M3 22v-6h6M21 12a9 9 0 0 1-15 6.7L3 16"/>
            </svg>
            {refreshing ? "更新中..." : "一键更新定价"}
          </button>
          {#if refreshMsg}
            <span class="text-xs {refreshMsg.ok ? 'text-[var(--green)]' : 'text-[var(--red)]'}">
              {refreshMsg.text}
            </span>
          {/if}
          <div class="toolbar-right">
            <div class="search-box">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
              <input type="text" placeholder="搜索模型..." bind:value={searchQuery} class="search-input" oninput={() => { currentPage = 1; }} />
            </div>
            <div class="page-size-group">
              {#each PAGE_SIZES as size}
                <button class="size-btn {pageSize === size ? 'active' : ''}" onclick={() => changePageSize(size)}>{size}</button>
              {/each}
            </div>
          </div>
        </div>

        <div class="overflow-x-auto">
          <table>
            <thead>
              <tr>
                <th>模型</th>
                <th class="text-right">输入 (¥/M)</th>
                <th class="text-right">输出 (¥/M)</th>
                <th class="text-right">缓存读取 (¥/M)</th>
                <th class="text-right">缓存写入 (¥/M)</th>
                <th class="text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {#each pagedData as item (item.model)}
                <tr>
                  <td class="font-semibold">{item.model}</td>
                  {#if editingModel === item.model}
                    <td class="text-right"><input class="price-input" type="number" step="0.01" bind:value={editForm.input_price} placeholder="¥" /></td>
                    <td class="text-right"><input class="price-input" type="number" step="0.01" bind:value={editForm.output_price} placeholder="¥" /></td>
                    <td class="text-right"><input class="price-input" type="number" step="0.01" bind:value={editForm.cache_read_price} placeholder="¥" /></td>
                    <td class="text-right"><input class="price-input" type="number" step="0.01" bind:value={editForm.cache_write_price} placeholder="¥" /></td>
                    <td class="text-right">
                      <div class="flex items-center justify-end gap-2">
                        <button class="save-btn" disabled={saving === item.model} onclick={() => saveEdit(item.model)}>
                          {saving === item.model ? "保存中..." : "保存"}
                        </button>
                        <button class="cancel-btn" onclick={cancelEdit}>取消</button>
                      </div>
                    </td>
                  {:else}
                    <td class="text-right text-[var(--text-2)]">¥{toCNY(item.input_price)}</td>
                    <td class="text-right text-[var(--text-2)]">¥{toCNY(item.output_price)}</td>
                    <td class="text-right text-[var(--text-2)]">¥{toCNY(item.cache_read_price)}</td>
                    <td class="text-right text-[var(--text-2)]">¥{toCNY(item.cache_write_price)}</td>
                    <td class="text-right">
                      <button class="edit-btn" onclick={() => startEdit(item)}>编辑</button>
                    </td>
                  {/if}
                </tr>
              {:else}
                <tr>
                  <td colspan="6" class="empty-row">暂无匹配模型</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>

        {#if totalPages > 1}
          <div class="pagination">
            <span class="text-xs text-[var(--text-3)]">
              第 {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, filteredData.length)} 条 / 共 {filteredData.length} 条
            </span>
            <div class="flex items-center gap-1">
              <button class="page-btn" disabled={currentPage <= 1} onclick={() => goToPage(1)} title="首页">&laquo;</button>
              <button class="page-btn" disabled={currentPage <= 1} onclick={() => goToPage(currentPage - 1)}>&lsaquo;</button>
              {#each pageNumbers() as p}
                <button class="page-btn {p === currentPage ? 'active' : ''}" onclick={() => goToPage(p)}>{p}</button>
              {/each}
              <button class="page-btn" disabled={currentPage >= totalPages} onclick={() => goToPage(currentPage + 1)}>&rsaquo;</button>
              <button class="page-btn" disabled={currentPage >= totalPages} onclick={() => goToPage(totalPages)} title="末页">&raquo;</button>
            </div>
          </div>
        {/if}

        {#if saveMsg}
          <div class="mt-3 text-sm {saveMsg.ok ? 'text-[var(--green)]' : 'text-[var(--red)]'}">
            {saveMsg.text}
          </div>
        {/if}
      {/if}
    </div>
  {/if}
</div>

<style>
  .pricing-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }
  .pricing-header {
    width: 100%;
    padding: 16px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    cursor: pointer;
    transition: background 0.2s;
    background: transparent;
    border: none;
    color: var(--text);
  }
  .pricing-header:hover {
    background: rgba(99, 102, 241, 0.05);
  }
  .chart-title {
    font-size: 14px;
    font-weight: 600;
  }
  .chevron {
    transition: transform 0.3s;
  }
  .chevron.open {
    transform: rotate(180deg);
  }
  .pricing-body {
    padding: 0 20px 20px;
    border-top: 1px solid var(--border);
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 16px;
    margin-bottom: 8px;
    flex-wrap: wrap;
  }
  .toolbar-right {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .search-box {
    display: flex;
    align-items: center;
    gap: 6px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 10px;
  }
  .search-box:focus-within {
    border-color: var(--primary);
  }
  .search-input {
    background: transparent;
    border: none;
    outline: none;
    color: var(--text);
    font-size: 12px;
    width: 140px;
  }
  .search-input::placeholder {
    color: var(--text-3);
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
  .refresh-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 7px 16px;
    border-radius: 8px;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
    border: 1px solid var(--primary);
    background: rgba(99, 102, 241, 0.1);
    color: var(--primary);
    font-weight: 500;
  }
  .refresh-btn:hover:not(:disabled) {
    background: var(--primary);
    color: #fff;
  }
  .refresh-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .spin-icon {
    transition: none;
  }
  .spin-icon.spinning {
    animation: spin 1s linear infinite;
  }
  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
  }
  th {
    padding: 10px 14px;
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
    padding: 10px 14px;
    font-size: 13px;
    border-bottom: 1px solid rgba(51, 65, 85, 0.4);
  }
  td.text-right {
    text-align: right;
  }
  tr:hover td {
    background: rgba(99, 102, 241, 0.06);
  }
  .empty-row {
    text-align: center;
    padding: 24px 16px;
    color: var(--text-3);
  }
  .price-input {
    width: 100px;
    padding: 4px 10px;
    font-size: 13px;
    text-align: right;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    outline: none;
  }
  .price-input:focus {
    border-color: var(--primary);
  }
  .edit-btn {
    padding: 4px 14px;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.2s;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-2);
  }
  .edit-btn:hover {
    border-color: var(--primary);
    color: var(--text);
  }
  .save-btn {
    padding: 4px 14px;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: opacity 0.2s;
    border: none;
    background: var(--primary);
    color: #fff;
  }
  .save-btn:hover {
    opacity: 0.85;
  }
  .save-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .cancel-btn {
    padding: 4px 14px;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.2s;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-3);
  }
  .cancel-btn:hover {
    border-color: var(--red);
    color: var(--red);
  }
  .pagination {
    padding: 12px 0;
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
