<script lang="ts">
  import type { TimeRange } from "../types";

  interface Props {
    current: TimeRange;
    onchange: (range: TimeRange, from?: string, to?: string) => void;
  }

  let { current, onchange }: Props = $props();

  const ranges: { key: TimeRange; label: string }[] = [
    { key: "today", label: "今日" },
    { key: "7d", label: "7 天" },
    { key: "30d", label: "30 天" },
    { key: "custom", label: "自定义" },
  ];

  let customFrom = $state("");
  let customTo = $state("");
  let showCustomInputs = $state(false);

  function selectRange(key: TimeRange) {
    if (key === "custom") {
      showCustomInputs = true;
    } else {
      showCustomInputs = false;
      onchange(key);
    }
  }

  function applyCustom() {
    onchange("custom", customFrom, customTo);
  }
</script>

<div class="flex items-center gap-2">
  {#each ranges as r}
    <button
      class="px-3 py-1.5 text-sm rounded-md transition-colors {(current === r.key || (r.key === 'custom' && showCustomInputs))
        ? 'bg-blue-600 text-white'
        : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white'}"
      onclick={() => selectRange(r.key)}
    >
      {r.label}
    </button>
  {/each}

  {#if showCustomInputs}
    <div class="flex items-center gap-2 ml-2">
      <input
        type="date"
        bind:value={customFrom}
        class="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white"
      />
      <span class="text-gray-500">-</span>
      <input
        type="date"
        bind:value={customTo}
        class="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white"
      />
      <button
        class="px-2 py-1 text-sm bg-blue-600 rounded hover:bg-blue-500"
        onclick={applyCustom}
      >
        应用
      </button>
    </div>
  {/if}
</div>
