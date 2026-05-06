<script lang="ts">
  import { onMount } from "svelte";

  interface Props {
    agents: string[];
    models: string[];
    selectedAgents: string[];
    selectedModels: string[];
    onchange: (agents: string[], models: string[]) => void;
  }

  let { agents, models, selectedAgents, selectedModels, onchange }: Props = $props();

  let showAgents = $state(false);
  let showModels = $state(false);
  let containerEl: HTMLDivElement | undefined = $state();

  function handleClickOutside(e: MouseEvent) {
    if (containerEl && !containerEl.contains(e.target as Node)) {
      showAgents = false;
      showModels = false;
    }
  }

  onMount(() => {
    document.addEventListener("click", handleClickOutside, true);
    return () => document.removeEventListener("click", handleClickOutside, true);
  });

  function toggleAgent(agent: string) {
    const next = selectedAgents.includes(agent)
      ? selectedAgents.filter((a) => a !== agent)
      : [...selectedAgents, agent];
    onchange(next, selectedModels);
  }

  function toggleModel(model: string) {
    const next = selectedModels.includes(model)
      ? selectedModels.filter((m) => m !== model)
      : [...selectedModels, model];
    onchange(selectedAgents, next);
  }

  function clearFilters() {
    onchange([], []);
  }
</script>

<!-- Fixed bottom bar with backdrop blur, h-14 (56px) -->
<div bind:this={containerEl} class="fixed bottom-0 left-0 right-0 bg-gray-800/95 backdrop-blur-sm border-t border-gray-700 px-6 py-3 flex items-center gap-4 z-50 h-14">
  <span class="text-xs text-gray-500 uppercase tracking-wide shrink-0">筛选:</span>

  <div class="relative">
    <button
      class="px-3 py-1 text-sm bg-gray-700 rounded hover:bg-gray-600 flex items-center gap-1"
      onclick={() => (showAgents = !showAgents)}
    >
      Agent ({selectedAgents.length || "全部"})
      <span class="text-xs">&#9662;</span>
    </button>
    {#if showAgents}
      <div
        class="absolute bottom-full mb-1 left-0 bg-gray-800 border border-gray-700 rounded shadow-xl min-w-40 max-h-60 overflow-auto"
      >
        {#each agents as agent}
          <label class="flex items-center gap-2 px-3 py-2 hover:bg-gray-700 cursor-pointer text-sm">
            <input
              type="checkbox"
              checked={selectedAgents.includes(agent)}
              onchange={() => toggleAgent(agent)}
              class="rounded"
            />
            {agent}
          </label>
        {/each}
        {#if agents.length === 0}
          <div class="px-3 py-2 text-gray-500 text-sm">暂无 Agent</div>
        {/if}
      </div>
    {/if}
  </div>

  <div class="relative">
    <button
      class="px-3 py-1 text-sm bg-gray-700 rounded hover:bg-gray-600 flex items-center gap-1"
      onclick={() => (showModels = !showModels)}
    >
      模型 ({selectedModels.length || "全部"})
      <span class="text-xs">&#9662;</span>
    </button>
    {#if showModels}
      <div
        class="absolute bottom-full mb-1 left-0 bg-gray-800 border border-gray-700 rounded shadow-xl min-w-48 max-h-60 overflow-auto"
      >
        {#each models as model}
          <label class="flex items-center gap-2 px-3 py-2 hover:bg-gray-700 cursor-pointer text-sm">
            <input
              type="checkbox"
              checked={selectedModels.includes(model)}
              onchange={() => toggleModel(model)}
              class="rounded"
            />
            {model}
          </label>
        {/each}
        {#if models.length === 0}
          <div class="px-3 py-2 text-gray-500 text-sm">暂无模型</div>
        {/if}
      </div>
    {/if}
  </div>

  <button
    class="px-3 py-1 text-sm text-gray-400 hover:text-white"
    onclick={clearFilters}
  >
    清除
  </button>
</div>
