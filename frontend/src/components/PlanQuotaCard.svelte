<script lang="ts">
  import { onMount } from "svelte";
  import type { QuotaSnapshot, ProviderInfo, QuotaWindow } from "../types";
  import { fetchQuota, refreshQuota, fetchProviders, updateProviderConfig } from "../api/client";

  let snapshots: QuotaSnapshot[] = $state([]);
  let providers: ProviderInfo[] = $state([]);
  let loading = $state(true);
  let refreshing = $state(false);
  let showSettings = $state(false);
  let savingProvider = $state<string | null>(null);
  let saveMsg = $state<{ provider: string; ok: boolean; text: string } | null>(null);

  // Settings form state per provider
  let settingsForms = $state<Record<string, { enabled: boolean; plan_type: string; session_token: string }>>({});

  function ratioColor(ratio: number): string {
    if (ratio >= 0.95) return "var(--red)";
    if (ratio >= 0.80) return "var(--amber)";
    return "var(--green)";
  }

  function formatNumber(n: number, unit: string): string {
    if (unit === "credits" && n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (unit === "credits" && n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return Math.round(n).toString();
  }

  function formatResetTime(resetAt: string | null): string {
    if (!resetAt) return "";
    try {
      const dt = new Date(resetAt);
      const now = new Date();
      const diffMs = dt.getTime() - now.getTime();
      if (diffMs <= 0) return "已重置";
      const hours = Math.floor(diffMs / (1000 * 60 * 60));
      const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
      if (hours > 24) return `${Math.floor(hours / 24)}天${hours % 24}h后`;
      return `${hours}h${minutes}m后`;
    } catch {
      return "";
    }
  }

  function sourceLabel(source: string): { text: string; color: string } {
    switch (source) {
      case "api": return { text: "实时", color: "var(--green)" };
      case "estimate": return { text: "估算", color: "var(--amber)" };
      case "error": return { text: "异常", color: "var(--red)" };
      default: return { text: source, color: "var(--text-3)" };
    }
  }

  function windowLabel(snapshot: QuotaSnapshot, idx: number): string {
    if (snapshot.provider === "zhipu") {
      return idx === 0 ? "5小时窗口" : "周额度";
    }
    return "本月额度";
  }

  async function loadData() {
    loading = true;
    try {
      const [quotaData, provData] = await Promise.all([fetchQuota(), fetchProviders()]);
      snapshots = quotaData.items;
      providers = provData;
      // Sync settings forms
      for (const p of provData) {
        settingsForms[p.provider_id] = {
          enabled: p.enabled,
          plan_type: p.plan_type || "pro",
          session_token: "",
        };
      }
    } catch (e: any) {
      console.warn("加载套餐余量失败:", e);
    } finally {
      loading = false;
    }
  }

  async function handleRefresh() {
    refreshing = true;
    saveMsg = null;
    try {
      const data = await refreshQuota();
      snapshots = data.items;
    } catch (e: any) {
      console.warn("刷新失败:", e);
    } finally {
      refreshing = false;
    }
  }

  async function saveSettings(providerId: string) {
    const form = settingsForms[providerId];
    if (!form) return;
    savingProvider = providerId;
    saveMsg = null;
    try {
      const updates: Partial<{ enabled: boolean; plan_type: string; session_token: string }> = {
        enabled: form.enabled,
        plan_type: form.plan_type,
      };
      // Only send session_token if user typed something (non-empty)
      if (form.session_token) {
        updates.session_token = form.session_token;
      }
      await updateProviderConfig(providerId, updates);
      saveMsg = { provider: providerId, ok: true, text: "已保存" };
      // Reload data
      await loadData();
    } catch (e: any) {
      saveMsg = { provider: providerId, ok: false, text: e.message || "保存失败" };
    } finally {
      savingProvider = null;
    }
  }

  onMount(() => {
    loadData();
  });
</script>

<div class="quota-section">
  <div class="quota-header">
    <div class="flex items-center gap-2">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2">
        <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/>
        <path d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12"/>
      </svg>
      <h3 class="section-title">套餐余量监控</h3>
      {#if snapshots.length > 0}
        <span class="text-[11px] text-[var(--text-3)]">({snapshots.length}个套餐)</span>
      {/if}
    </div>
    <div class="flex items-center gap-2">
      <button class="refresh-btn" onclick={handleRefresh} disabled={refreshing || loading}>
        <svg class="spin-icon {refreshing ? 'spinning' : ''}" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 2v6h-6M3 12a9 9 0 0 1 15-6.7L21 8M3 22v-6h6M21 12a9 9 0 0 1-15 6.7L3 16"/>
        </svg>
        {refreshing ? "刷新中..." : "刷新"}
      </button>
      <button class="settings-btn" onclick={() => (showSettings = !showSettings)}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09a1.65 1.65 0 00-1-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09a1.65 1.65 0 001.51-1 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z"/>
        </svg>
        设置
      </button>
    </div>
  </div>

  {#if showSettings}
    <div class="settings-panel">
      {#each providers as p (p.provider_id)}
        {@const form = settingsForms[p.provider_id]}
        {#if form}
          <div class="settings-row">
            <div class="settings-info">
              <span class="font-semibold text-sm">{p.display_name}</span>
              <span class="text-[11px] {p.enabled ? 'text-[var(--green)]' : 'text-[var(--text-3)]'}">
                {p.enabled ? (p.has_credential ? "已启用 · 实时查询" : "已启用 · 估算模式") : "未启用"}
              </span>
            </div>
            <div class="settings-controls">
              <label class="toggle-label">
                <input type="checkbox" bind:checked={form.enabled} />
                <span class="text-xs">启用</span>
              </label>
              <select bind:value={form.plan_type} class="plan-select">
                {#if p.provider_id === "zhipu"}
                  <option value="lite">Lite</option>
                  <option value="pro">Pro</option>
                  <option value="max">Max</option>
                {:else if p.provider_id === "xiaomi"}
                  <option value="lite">Lite</option>
                  <option value="standard">Standard</option>
                  <option value="pro">Pro</option>
                  <option value="max">Max</option>
                {/if}
              </select>
              <input
                type="password"
                placeholder="Session Token / Cookie"
                bind:value={form.session_token}
                class="token-input"
              />
              <button class="save-btn" disabled={savingProvider === p.provider_id} onclick={() => saveSettings(p.provider_id)}>
                {savingProvider === p.provider_id ? "保存中..." : "保存"}
              </button>
            </div>
            {#if saveMsg && saveMsg.provider === p.provider_id}
              <span class="text-xs {saveMsg.ok ? 'text-[var(--green)]' : 'text-[var(--red)]'}">{saveMsg.text}</span>
            {/if}
          </div>
        {/if}
      {/each}
      <div class="settings-hint">
        <span class="text-[11px] text-[var(--text-3)]">
          <strong>智谱：</strong>填 API key（自动走本地估算），或登录 bigmodel.cn 从 Network 面板复制 Cookie（实时查询）。<br />
          <strong>小米：</strong>必须从 Network 面板复制完整 Cookie（包含 HttpOnly 的 serviceToken），document.cookie 拿不到。
        </span>
      </div>
    </div>
  {/if}

  {#if loading}
    <div class="loading-area">
      <span class="text-xs text-[var(--text-3)]">加载套餐数据...</span>
    </div>
  {:else if snapshots.length === 0}
    <div class="empty-area">
      <span class="text-xs text-[var(--text-3)]">未启用任何套餐监控，请点击"设置"启用</span>
    </div>
  {:else}
    <div class="cards-grid">
      {#each snapshots as snap (snap.provider)}
        {@const sl = sourceLabel(snap.source)}
        {@const allWindows = [snap.main_window, ...snap.extra_windows].filter((w) => w !== null) as QuotaWindow[]}
        <div class="quota-card">
          <div class="card-top">
            <div>
              <span class="card-title">{snap.display_name}</span>
              <span class="plan-badge plan-{snap.plan_type}">{snap.plan_name}</span>
            </div>
            <span class="source-badge" style="color: {sl.color}; border-color: {sl.color};">{sl.text}</span>
          </div>

          {#if snap.error}
            <div class="error-box">
              <span class="text-[11px] text-[var(--red)]">{snap.error}</span>
            </div>
          {/if}

          <div class="windows-area">
            {#each allWindows as win, idx (idx)}
              {@const pct = Math.min(100, win.ratio * 100)}
              {@const color = ratioColor(win.ratio)}
              <div class="window-item">
                <div class="window-header">
                  <span class="window-label">{windowLabel(snap, idx)}</span>
                  <span class="window-value">
                    {formatNumber(win.used, win.unit)} / {formatNumber(win.total, win.unit)}
                    <span class="text-[var(--text-3)] text-[10px] ml-1">{win.unit}</span>
                  </span>
                </div>
                <div class="progress-bar">
                  <div class="progress-fill" style="width: {pct}%; background: {color};"></div>
                </div>
                <div class="window-footer">
                  <span class="text-[10px] text-[var(--text-3)]">{pct.toFixed(1)}% 已用</span>
                  {#if win.reset_at}
                    <span class="text-[10px] text-[var(--text-3)]">重置: {formatResetTime(win.reset_at)}</span>
                  {/if}
                </div>
              </div>
            {/each}
          </div>

          <div class="card-bottom">
            {#if snap.balance !== null}
              <span class="text-[10px] text-[var(--text-3)]">余额: ¥{snap.balance.toFixed(2)}</span>
            {/if}
            {#if snap.free_balance !== null}
              <span class="text-[10px] text-[var(--text-3)]">赠金: ¥{snap.free_balance.toFixed(2)}</span>
            {/if}
            {#if snap.expires_at}
              <span class="text-[10px] text-[var(--text-3)]">到期: {snap.expires_at.slice(0, 10)}</span>
            {/if}
          </div>

          {#if snap.model_multipliers.length > 0}
            <div class="multipliers-area">
              {#each snap.model_multipliers.filter((m) => m.peak > 1 || m.off_peak < 1) as mult (mult.model)}
                <span class="mult-badge">
                  {mult.model}
                  {#if mult.peak > 1}
                    <span class="mult-coeff">高峰{mult.peak}x</span>
                  {/if}
                  {#if mult.off_peak < 1}
                    <span class="mult-coeff green">夜间{mult.off_peak}x</span>
                  {/if}
                </span>
              {/each}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .quota-section {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 20px;
  }
  .quota-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 14px;
    flex-wrap: wrap;
    gap: 8px;
  }
  .section-title {
    font-size: 14px;
    font-weight: 600;
  }
  .refresh-btn, .settings-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 12px;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-2);
  }
  .refresh-btn:hover:not(:disabled), .settings-btn:hover {
    border-color: var(--primary);
    color: var(--primary);
  }
  .refresh-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .spin-icon.spinning {
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  /* Settings panel */
  .settings-panel {
    border-top: 1px solid var(--border);
    padding-top: 14px;
    margin-bottom: 14px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .settings-row {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .settings-info {
    display: flex;
    flex-direction: column;
    min-width: 160px;
  }
  .settings-controls {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .toggle-label {
    display: flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
    color: var(--text-2);
  }
  .plan-select {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
    color: var(--text);
    outline: none;
  }
  .token-input {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 12px;
    color: var(--text);
    outline: none;
    width: 200px;
  }
  .token-input:focus {
    border-color: var(--primary);
  }
  .settings-hint {
    padding-top: 4px;
  }
  .settings-hint code {
    background: var(--bg);
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 11px;
  }

  /* Cards */
  .cards-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 14px;
  }
  .quota-card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .card-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .card-title {
    font-size: 13px;
    font-weight: 600;
    margin-right: 8px;
  }
  .plan-badge {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
  }
  .plan-lite { background: rgba(148, 163, 184, 0.2); color: var(--text-2); }
  .plan-standard { background: rgba(59, 130, 246, 0.2); color: var(--blue); }
  .plan-pro { background: rgba(99, 102, 241, 0.2); color: var(--primary-hover); }
  .plan-max { background: rgba(139, 92, 246, 0.2); color: var(--purple); }
  .source-badge {
    font-size: 10px;
    font-weight: 500;
    padding: 1px 7px;
    border-radius: 3px;
    border: 1px solid;
  }

  .error-box {
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 4px;
    padding: 5px 8px;
  }

  .windows-area {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .window-item {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .window-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .window-label {
    font-size: 11px;
    color: var(--text-2);
  }
  .window-value {
    font-size: 12px;
    font-weight: 500;
    color: var(--text);
  }
  .progress-bar {
    height: 6px;
    background: rgba(51, 65, 85, 0.4);
    border-radius: 3px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.5s ease;
  }
  .window-footer {
    display: flex;
    justify-content: space-between;
  }
  .card-bottom {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    padding-top: 4px;
    border-top: 1px solid rgba(51, 65, 85, 0.3);
  }
  .multipliers-area {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .mult-badge {
    font-size: 10px;
    padding: 2px 6px;
    background: rgba(245, 158, 11, 0.1);
    border: 1px solid rgba(245, 158, 11, 0.3);
    border-radius: 3px;
    color: var(--amber);
    display: flex;
    align-items: center;
    gap: 3px;
  }
  .mult-coeff {
    font-weight: 600;
  }
  .mult-coeff.green {
    color: var(--green);
  }

  .loading-area, .empty-area {
    padding: 20px 0;
    text-align: center;
  }
  .save-btn {
    padding: 4px 14px;
    border-radius: 4px;
    font-size: 12px;
    cursor: pointer;
    border: none;
    background: var(--primary);
    color: #fff;
    transition: opacity 0.2s;
  }
  .save-btn:hover:not(:disabled) {
    opacity: 0.85;
  }
  .save-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
