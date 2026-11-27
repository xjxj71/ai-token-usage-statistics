<script lang="ts">
  import { uiState, toggleCollapsed } from "../ui.svelte.ts";

  interface Props {
    current: string;
    onNavigate: (view: string) => void;
    sseConnected: boolean;
    version?: string;
  }

  let { current, onNavigate, sseConnected, version = "" }: Props = $props();

  const ITEMS = [
    { id: "overview", label: "概览", icon: '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>' },
    { id: "trends", label: "趋势分析", icon: '<path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/>' },
    { id: "sessions", label: "会话明细", icon: '<path d="M21 12a9 9 0 11-9-9"/><path d="M12 7v5l3 3"/>' },
    { id: "records", label: "使用记录", icon: '<path d="M4 6h16M4 12h16M4 18h10"/>' },
    { id: "monitor", label: "实时监控", icon: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>' },
    { id: "pricing", label: "模型定价", icon: '<path d="M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/>' },
    { id: "data", label: "数据管理", icon: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/>' },
  ];

  const activeIndex = $derived(Math.max(0, ITEMS.findIndex((i) => i.id === current)));
</script>

<aside class="sidebar" class:collapsed={uiState.collapsed}>
  <div class="brand">
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2">
      <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
    </svg>
    <div class="brand-text">
      <div class="brand-name">Token 统计</div>
      <div class="brand-sub">AI Usage Dashboard</div>
    </div>
  </div>

  <nav class="nav" aria-label="主导航">
    <div class="nav-pill" style="transform: translateY({activeIndex * 38}px)"></div>
    {#each ITEMS as item (item.id)}
      <button
        class="nav-item"
        class:active={current === item.id}
        aria-current={current === item.id ? "page" : undefined}
        onclick={() => onNavigate(item.id)}
        title={item.label}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">{@html item.icon}</svg>
        <span class="nav-label">{item.label}</span>
        {#if item.id === "monitor"}
          <span class="nav-live" class:on={sseConnected}></span>
        {/if}
      </button>
    {/each}
  </nav>

  <button class="collapse-btn" onclick={toggleCollapsed} title={uiState.collapsed ? "展开侧栏" : "折叠侧栏（仅图标）"}>
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      {#if uiState.collapsed}
        <path d="M13 17l5-5-5-5M6 17l5-5-5-5"/>
      {:else}
        <path d="M11 17l-5-5 5-5M18 17l-5-5 5-5"/>
      {/if}
    </svg>
  </button>

  <div class="side-foot">
    <div class="sse" class:off={!sseConnected}>
      <span class="sse-dot"></span>{sseConnected ? "实时连接" : "连接断开"}
    </div>
    {#if version}<div class="ver">v{version}</div>{/if}
  </div>
</aside>

<style>
  .sidebar {
    width: 208px;
    flex-shrink: 0;
    transition: width .28s cubic-bezier(.3, .8, .3, 1);
    background: var(--card);
    border-right: 1px solid var(--border);
    padding: 18px 12px 14px;
    position: sticky;
    top: 0;
    height: 100vh;
    display: flex;
    flex-direction: column;
    z-index: 20;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 10px 18px;
  }
  .brand-name { font-weight: 700; font-size: 14px; }
  .brand-sub { font-size: 9px; color: var(--text-3); letter-spacing: .5px; }
  .nav {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .nav-pill {
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    height: 36px;
    border-radius: 9px;
    background: rgba(var(--primary-rgb), 0.12);
    transition: transform .3s cubic-bezier(.3, .8, .3, 1);
    z-index: 0;
  }
  .nav-item {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 10px;
    height: 36px;
    padding: 0 12px;
    border: 0;
    background: transparent;
    border-radius: 9px;
    font-size: 12.5px;
    font-family: inherit;
    color: var(--text-2);
    cursor: pointer;
    transition: color .2s;
    text-align: left;
  }
  .nav-item:hover:not(.active) { color: var(--text); }
  .nav-item.active { color: var(--primary); font-weight: 600; }
  .nav-label { flex: 1; }
  .nav-live {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--text-3);
  }
  .nav-live.on {
    background: var(--green);
    box-shadow: 0 0 6px var(--green);
    animation: pulse-dot 2s infinite;
  }
  @keyframes pulse-dot { 50% { opacity: .4; } }
  .side-foot {
    margin-top: auto;
    padding: 10px 12px 0;
    font-size: 10px;
    color: var(--text-3);
  }
  .sse { display: flex; align-items: center; gap: 6px; color: var(--green); margin-bottom: 4px; }
  .sse.off { color: var(--red); }
  .sse-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; animation: pulse-dot 2s infinite; }
  .sse.off .sse-dot { animation: none; }
  .ver { color: var(--text-3); }

  .collapse-btn {
    margin-top: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    height: 30px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    transition: all .2s;
  }
  .collapse-btn:hover { color: var(--text); border-color: rgba(var(--primary-rgb), .4); }

  /* 手动折叠：仅图标，右侧内容随 flex 自适应加宽 */
  .sidebar.collapsed { width: 62px; padding: 18px 8px 14px; }
  .sidebar.collapsed .brand { justify-content: center; padding: 0 0 18px; }
  .sidebar.collapsed .brand-text,
  .sidebar.collapsed .nav-label,
  .sidebar.collapsed .side-foot { display: none; }
  .sidebar.collapsed .nav-item { justify-content: center; padding: 0; }
  .sidebar.collapsed .nav-live { position: absolute; right: 6px; top: 6px; }

  @media (max-width: 1100px) {
    .sidebar { width: 62px; padding: 18px 8px 14px; }
    .brand { justify-content: center; padding: 0 0 18px; }
    .brand-text, .nav-label, .side-foot { display: none; }
    .nav-item { justify-content: center; padding: 0; }
    .nav-live { position: absolute; right: 6px; top: 6px; }
    .collapse-btn { display: none; }
  }
</style>