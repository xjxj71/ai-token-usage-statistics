<script lang="ts">
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

<div class="fixed bottom-0 left-0 right-0 bg-gray-800 border-t border-gray-700 px-6 py-3 flex items-center gap-4 z-50">
  <span class="text-xs text-gray-500 uppercase tracking-wide">Filters:</span>

  <div class="relative">
    <button
      class="px-3 py-1 text-sm bg-gray-700 rounded hover:bg-gray-600 flex items-center gap-1"
      onclick={() => (showAgents = !showAgents)}
    >
      Agent ({selectedAgents.length || "All"})
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
          <div class="px-3 py-2 text-gray-500 text-sm">No agents yet</div>
        {/if}
      </div>
    {/if}
  </div>

  <div class="relative">
    <button
      class="px-3 py-1 text-sm bg-gray-700 rounded hover:bg-gray-600 flex items-center gap-1"
      onclick={() => (showModels = !showModels)}
    >
      Model ({selectedModels.length || "All"})
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
          <div class="px-3 py-2 text-gray-500 text-sm">No models yet</div>
        {/if}
      </div>
    {/if}
  </div>

  <button
    class="px-3 py-1 text-sm text-gray-400 hover:text-white"
    onclick={clearFilters}
  >
    Clear
  </button>
</div>
