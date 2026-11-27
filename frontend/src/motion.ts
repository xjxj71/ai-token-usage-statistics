// 动效工具：数字滚动 action（Svelte use:countUp）。
// 纯函数 action，不含 runes，可放在普通 .ts。
// 用法：<span use:countUp={{ value: n, format: fmt }}>0</span>
// value 变化时从旧值滚到新值；首次挂载从 0 滚入。

export interface CountUpOpts {
  value: number;
  format: (n: number) => string;
  duration?: number;
}

export function countUp(node: HTMLElement, opts: CountUpOpts) {
  let raf = 0;
  let from = 0;
  let current = opts.value;

  function animate(to: number) {
    cancelAnimationFrame(raf);
    const start = performance.now();
    const duration = opts.duration ?? 850;
    const a = from;
    function tick(now: number) {
      const t = Math.min(1, (now - start) / duration);
      const e = 1 - Math.pow(1 - t, 3);
      node.textContent = opts.format(a + (to - a) * e);
      if (t < 1) raf = requestAnimationFrame(tick);
      else from = to;
    }
    raf = requestAnimationFrame(tick);
  }

  node.textContent = opts.format(0);
  animate(opts.value);

  return {
    update(next: CountUpOpts) {
      opts = next;
      if (next.value !== current) {
        current = next.value;
        animate(next.value);
      }
    },
    destroy() {
      cancelAnimationFrame(raf);
    },
  };
}

/** 与 StatCard 一致的数值格式化 */
export function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return Math.round(n).toLocaleString();
}