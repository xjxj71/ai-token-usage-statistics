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

/** 鼠标跟随 3D 倾斜 + 光斑坐标。
 *  rAF 插值（lerp 0.14）保证平滑，离开时缓动归位；
 *  同时写入 --mx/--my 供卡片光斑伪元素定位。
 *  指针驱动的微交互由用户鼠标直接控制，不做 reduced-motion 门禁
 *  （该偏好仅约束无限循环/自主动画，见 CSS 侧）。 */
export function tilt(node: HTMLElement, opts?: { max?: number }) {
  const max = opts?.max ?? 4.5;
  let tx = 0, ty = 0, cx = 0, cy = 0;
  let lift = 0, liftT = 0;
  let scale = 1, scaleT = 1;
  let raf = 0, hovering = false;

  function loop() {
    cx += (tx - cx) * 0.14;
    cy += (ty - cy) * 0.14;
    lift += (liftT - lift) * 0.14;
    scale += (scaleT - scale) * 0.14;
    node.style.transform =
      `perspective(900px) rotateX(${cx.toFixed(2)}deg) rotateY(${cy.toFixed(2)}deg) translateY(${lift.toFixed(2)}px) scale(${scale.toFixed(3)})`;
    const settled = !hovering && Math.abs(cx) < 0.02 && Math.abs(cy) < 0.02 && Math.abs(lift) < 0.05 && Math.abs(scale - 1) < 0.001;
    if (settled) {
      node.style.transform = "";
      raf = 0;
    } else {
      raf = requestAnimationFrame(loop);
    }
  }
  function kick() {
    if (!raf) raf = requestAnimationFrame(loop);
  }
  function onEnter() {
    hovering = true;
    liftT = -4;
    scaleT = 1.015;
    node.classList.add("tilting");
    kick();
  }
  function onMove(e: PointerEvent) {
    const r = node.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    tx = (0.5 - py) * max * 2;
    ty = (px - 0.5) * max * 2;
    node.style.setProperty("--mx", (px * 100).toFixed(1) + "%");
    node.style.setProperty("--my", (py * 100).toFixed(1) + "%");
    kick();
  }
  function onLeave() {
    hovering = false;
    liftT = 0;
    scaleT = 1;
    tx = 0;
    ty = 0;
    node.classList.remove("tilting");
    kick();
  }

  node.addEventListener("pointerenter", onEnter);
  node.addEventListener("pointermove", onMove);
  node.addEventListener("pointerleave", onLeave);
  return {
    destroy() {
      cancelAnimationFrame(raf);
      node.removeEventListener("pointerenter", onEnter);
      node.removeEventListener("pointermove", onMove);
      node.removeEventListener("pointerleave", onLeave);
    },
  };
}

/** 页面级环境光：跟随鼠标的柔和 radial 光晕（写入 --gx/--gy）。
 *  指针驱动，不做 reduced-motion 门禁。 */
export function cursorGlow(node: HTMLElement) {
  let raf = 0;
  let ev: PointerEvent | null = null;
  function onMove(e: PointerEvent) {
    ev = e;
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      if (ev) {
        node.style.setProperty("--gx", ev.clientX + "px");
        node.style.setProperty("--gy", ev.clientY + "px");
      }
    });
  }
  node.addEventListener("pointermove", onMove, { passive: true });
  return {
    destroy() {
      cancelAnimationFrame(raf);
      node.removeEventListener("pointermove", onMove);
    },
  };
}