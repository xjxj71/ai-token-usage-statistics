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
  let saving = $state<string | null>(null);  // 正在保存的模型名
  let editingModel: string | null = $state(null);
  let editForm = $state({ input_price: 0, output_price: 0, cache_read_price: 0, cache_write_price: 0 });
  let saveMsg = $state<{ model: string; ok: boolean; text: string } | null>(null);

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
      // 更新本地数据
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

  onMount(() => {
    loadPricing();
  });
</script>

<div class="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
  <div class="px-4 py-3 border-b border-gray-700 flex justify-between items-center">
    <h3 class="text-sm text-gray-400">模型费用定价</h3>
    <span class="text-xs text-gray-500">共 {pricingData.length} 个模型</span>
  </div>

  {#if loading}
    <div class="flex items-center justify-center py-12 text-gray-500">
      <svg class="animate-spin h-5 w-5 mr-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      加载中...
    </div>
  {:else}
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-gray-700 text-gray-500 text-left">
            <th class="px-4 py-2 font-medium">模型</th>
            <th class="px-4 py-2 font-medium text-right">输入 ($/M)</th>
            <th class="px-4 py-2 font-medium text-right">输出 ($/M)</th>
            <th class="px-4 py-2 font-medium text-right">缓存读取 ($/M)</th>
            <th class="px-4 py-2 font-medium text-right">缓存写入 ($/M)</th>
            <th class="px-4 py-2 font-medium text-center">操作</th>
          </tr>
        </thead>
        <tbody>
          {#each pricingData as item}
            {@const isEditing = editingModel === item.model}
            <tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
              <td class="px-4 py-2 text-gray-300 font-mono text-xs">
                {item.model}
              </td>
              {#if isEditing}
                <td class="px-2 py-1">
                  <input
                    type="number"
                    step="0.001"
                    bind:value={editForm.input_price}
                    class="w-20 px-1 py-0.5 text-xs text-right bg-gray-700 border border-gray-600 rounded text-white focus:border-blue-500 focus:outline-none"
                  />
                </td>
                <td class="px-2 py-1">
                  <input
                    type="number"
                    step="0.001"
                    bind:value={editForm.output_price}
                    class="w-20 px-1 py-0.5 text-xs text-right bg-gray-700 border border-gray-600 rounded text-white focus:border-blue-500 focus:outline-none"
                  />
                </td>
                <td class="px-2 py-1">
                  <input
                    type="number"
                    step="0.001"
                    bind:value={editForm.cache_read_price}
                    class="w-20 px-1 py-0.5 text-xs text-right bg-gray-700 border border-gray-600 rounded text-white focus:border-blue-500 focus:outline-none"
                  />
                </td>
                <td class="px-2 py-1">
                  <input
                    type="number"
                    step="0.001"
                    bind:value={editForm.cache_write_price}
                    class="w-20 px-1 py-0.5 text-xs text-right bg-gray-700 border border-gray-600 rounded text-white focus:border-blue-500 focus:outline-none"
                  />
                </td>
                <td class="px-2 py-1 text-center whitespace-nowrap">
                  <button
                    class="px-2 py-0.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
                    disabled={saving === item.model}
                    onclick={() => saveEdit(item.model)}
                  >
                    {saving === item.model ? "保存中..." : "保存"}
                  </button>
                  <button
                    class="px-2 py-0.5 text-xs rounded text-gray-400 hover:text-white ml-1"
                    onclick={cancelEdit}
                  >
                    取消
                  </button>
                </td>
              {:else}
                <td class="px-4 py-2 text-right text-gray-400">${item.input_price.toFixed(3)}</td>
                <td class="px-4 py-2 text-right text-gray-400">${item.output_price.toFixed(3)}</td>
                <td class="px-4 py-2 text-right text-gray-400">${item.cache_read_price.toFixed(3)}</td>
                <td class="px-4 py-2 text-right text-gray-400">${item.cache_write_price.toFixed(3)}</td>
                <td class="px-4 py-2 text-center">
                  {#if saveMsg && saveMsg.model === item.model}
                    <span class="text-xs {saveMsg.ok ? 'text-green-400' : 'text-red-400'}">{saveMsg.text}</span>
                  {:else}
                    <button
                      class="px-2 py-0.5 text-xs rounded text-blue-400 hover:bg-gray-700"
                      onclick={() => startEdit(item)}
                    >
                      编辑
                    </button>
                  {/if}
                </td>
              {/if}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
