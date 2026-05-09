<script lang="ts">
  import type { TokenRecord } from "../types";

  interface Props {
    items: TokenRecord[];
    total: number;
    page: number;
    pageSize: number;
    onPageChange: (page: number) => void;
  }

  let { items, total, page, pageSize, onPageChange }: Props = $props();

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

  let totalPages = $derived(Math.max(1, Math.ceil(total / pageSize)));
  let jumpPage = $state("");

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
    if (e.key === "Enter") {
      handleJump();
    }
  }
</script>

<div class="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
  <div class="px-4 py-3 border-b border-gray-700 flex justify-between items-center">
    <h3 class="text-sm text-gray-400">最近使用记录</h3>
    <span class="text-xs text-gray-500">共 {total} 条</span>
  </div>

  <div class="overflow-x-auto">
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-gray-700 text-gray-500 text-left">
          <th class="px-4 py-2 font-medium">时间</th>
          <th class="px-4 py-2 font-medium">Agent</th>
          <th class="px-4 py-2 font-medium">模型</th>
          <th class="px-4 py-2 font-medium text-right">输入</th>
          <th class="px-4 py-2 font-medium text-right">输出</th>
          <th class="px-4 py-2 font-medium text-right">缓存</th>
          <th class="px-4 py-2 font-medium text-right">费用</th>
        </tr>
      </thead>
      <tbody>
        {#each items as item}
          <tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
            <td class="px-4 py-2 text-gray-400">{fmtTime(item.timestamp)}</td>
            <td class="px-4 py-2">
              <span
                class="px-2 py-0.5 rounded text-xs {item.agent === 'claude-code'
                  ? 'bg-blue-900 text-blue-300'
                  : item.agent === 'hermes'
                    ? 'bg-green-900 text-green-300'
                    : 'bg-red-900 text-red-300'}"
              >
                {item.agent}
              </span>
            </td>
            <td class="px-4 py-2 text-gray-300">{item.model}</td>
            <td class="px-4 py-2 text-right text-gray-400">{fmt(item.input_tokens)}</td>
            <td class="px-4 py-2 text-right text-gray-400">{fmt(item.output_tokens)}</td>
            <td class="px-4 py-2 text-right text-gray-400">
              {fmt(item.cache_read_tokens + item.cache_write_tokens)}
            </td>
            <td class="px-4 py-2 text-right text-yellow-400">${item.cost_usd.toFixed(4)}</td>
          </tr>
        {:else}
          <tr>
            <td colspan="7" class="px-4 py-8 text-center text-gray-500">暂无使用记录</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <!-- Enhanced Pagination UI -->
  {#if totalPages > 1}
    <div class="px-4 py-3 border-t border-gray-700 flex items-center justify-between flex-wrap gap-2">
      <span class="text-xs text-gray-500">
        第 {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} 条 / 共 {total} 条，共 {totalPages} 页
      </span>
      <div class="flex items-center gap-1">
        <!-- 首页 -->
        <button
          class="px-2 py-1 text-xs rounded {page <= 1 ? 'text-gray-600 cursor-not-allowed' : 'text-gray-400 hover:bg-gray-700'}"
          disabled={page <= 1}
          onclick={() => onPageChange(1)}
          title="首页"
        >
          ««
        </button>
        <!-- 上一页 -->
        <button
          class="px-2 py-1 text-xs rounded {page <= 1 ? 'text-gray-600 cursor-not-allowed' : 'text-gray-400 hover:bg-gray-700'}"
          disabled={page <= 1}
          onclick={() => onPageChange(page - 1)}
        >
          上一页
        </button>
        <!-- 页码 -->
        {#each pageNumbers() as p}
          <button
            class="px-2.5 py-1 text-xs rounded {p === page ? 'bg-blue-600 text-white' : 'text-gray-400 hover:bg-gray-700'}"
            onclick={() => onPageChange(p)}
          >
            {p}
          </button>
        {/each}
        <!-- 下一页 -->
        <button
          class="px-2 py-1 text-xs rounded {page >= totalPages ? 'text-gray-600 cursor-not-allowed' : 'text-gray-400 hover:bg-gray-700'}"
          disabled={page >= totalPages}
          onclick={() => onPageChange(page + 1)}
        >
          下一页
        </button>
        <!-- 末页 -->
        <button
          class="px-2 py-1 text-xs rounded {page >= totalPages ? 'text-gray-600 cursor-not-allowed' : 'text-gray-400 hover:bg-gray-700'}"
          disabled={page >= totalPages}
          onclick={() => onPageChange(totalPages)}
          title="末页"
        >
          »»
        </button>
        <!-- 跳转 -->
        <span class="text-xs text-gray-500 ml-2">跳至</span>
        <input
          type="number"
          bind:value={jumpPage}
          onkeydown={handleJumpKeydown}
          min="1"
          max={totalPages}
          class="w-12 px-1 py-0.5 text-xs text-center bg-gray-700 border border-gray-600 rounded text-white focus:border-blue-500 focus:outline-none"
          placeholder=""
        />
        <button
          class="px-2 py-1 text-xs rounded text-gray-400 hover:bg-gray-700"
          onclick={handleJump}
        >
          Go
        </button>
      </div>
    </div>
  {/if}
</div>
