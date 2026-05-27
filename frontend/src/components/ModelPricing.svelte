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

  let pricingData: PricingItem[] = $state([]);
  let loading = $state(true);
  let saving = $state<string | null>(null);
  let editingModel: string | null = $state(null);
  let editForm = $state({ input_price: 0, output_price: 0, cache_read_price: 0, cache_write_price: 0 });
  let saveMsg = $state<{ model: string; ok: boolean; text: string } | null>(null);
  let expanded = $state(false);

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
      input_price: item.input_price,
      output_price: item.output_price,
      cache_read_price: item.cache_read_price,
      cache_write_price: item.cache_write_price,
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
      const res = await fetch(`${BASE}/pricing/${encoded}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editForm),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "保存失败");
      }
      pricingData = pricingData.map((p) =>
        p.model === model ? { ...p, ...editForm } : p
      );
      saveMsg = { model, ok: true, text: "已保存" };
      editingModel = null;
    } catch (e: any) {
      saveMsg = { model, ok: false, text: e.message || "保存失败" };
    } finally {
      saving = null;
    }
  }

  function toggleExpand() {
    expanded = !expanded;
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
        <div class="overflow-x-auto">
          <table>
            <thead>
              <tr>
                <th>模型</th>
                <th class="text-right">输入 ($/1M)</th>
                <th class="text-right">输出 ($/1M)</th>
                <th class="text-right">缓存读取 ($/1M)</th>
                <th class="text-right">缓存写入 ($/1M)</th>
                <th class="text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {#each pricingData as item}
                <tr>
                  <td class="font-semibold">{item.model}</td>
                  {#if editingModel === item.model}
                    <td class="text-right"><input class="price-input" type="number" step="0.01" bind:value={editForm.input_price} /></td>
                    <td class="text-right"><input class="price-input" type="number" step="0.01" bind:value={editForm.output_price} /></td>
                    <td class="text-right"><input class="price-input" type="number" step="0.01" bind:value={editForm.cache_read_price} /></td>
                    <td class="text-right"><input class="price-input" type="number" step="0.01" bind:value={editForm.cache_write_price} /></td>
                    <td class="text-right">
                      <div class="flex items-center justify-end gap-2">
                        <button class="save-btn" disabled={saving === item.model} onclick={() => saveEdit(item.model)}>
                          {saving === item.model ? "保存中..." : "保存"}
                        </button>
                        <button class="cancel-btn" onclick={cancelEdit}>取消</button>
                      </div>
                    </td>
                  {:else}
                    <td class="text-right text-[var(--text-2)]">${item.input_price.toFixed(2)}</td>
                    <td class="text-right text-[var(--text-2)]">${item.output_price.toFixed(2)}</td>
                    <td class="text-right text-[var(--text-2)]">${item.cache_read_price.toFixed(2)}</td>
                    <td class="text-right text-[var(--text-2)]">${item.cache_write_price.toFixed(2)}</td>
                    <td class="text-right">
                      <button class="edit-btn" onclick={() => startEdit(item)}>编辑</button>
                    </td>
                  {/if}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>

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
  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 16px;
  }
  th {
    text-align: left;
    padding: 10px 14px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-3);
    border-bottom: 1px solid var(--border);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  td {
    padding: 10px 14px;
    font-size: 13px;
    border-bottom: 1px solid rgba(51, 65, 85, 0.4);
  }
  tr:hover td {
    background: rgba(99, 102, 241, 0.06);
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
</style>
