// 动效工具库：数字滚动 / 交错入场 / 图表绘制 / 滚动显现 / 迷你 sparkline
// 依赖 _shared.js 的数据与图表函数（先引入 _shared.js 再引入本文件）。

// 数字滚动（ease-out cubic）
function countUp(el, target, opts = {}) {
  const duration = opts.duration ?? 900;
  const fmt = opts.fmt ?? ((n) => Math.round(n).toLocaleString());
  const start = performance.now();
  function tick(now) {
    const t = Math.min(1, (now - start) / duration);
    const e = 1 - Math.pow(1 - t, 3);
    el.textContent = fmt(target * e);
    if (t < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

// 给容器子元素打交错入场标记（配合 .stagger CSS）
function stagger(container, step = 60) {
  [...container.children].forEach((c, i) => c.style.setProperty('--i', i));
  container.classList.add('stagger');
}

// 折线绘制动画：pathLength=1 + dashoffset 1→0；面积淡入
function animateLines(svg, delay = 0) {
  svg.querySelectorAll('path').forEach((p) => {
    const stroke = p.getAttribute('stroke');
    if (stroke && stroke !== 'none') {
      p.setAttribute('pathLength', '1');
      p.style.strokeDasharray = '1';
      p.style.strokeDashoffset = '1';
      p.style.transition = `stroke-dashoffset 1.1s cubic-bezier(.4,0,.2,1) ${delay}ms`;
      requestAnimationFrame(() => requestAnimationFrame(() => { p.style.strokeDashoffset = '0'; }));
    } else if ((p.getAttribute('fill') || '').startsWith('url')) {
      p.style.opacity = '0';
      p.style.transition = `opacity .9s ease ${delay + 500}ms`;
      requestAnimationFrame(() => requestAnimationFrame(() => { p.style.opacity = '1'; }));
    }
  });
}

// 环形图扫入：dasharray 从 0 过渡到目标
function animateDonut(svg, delay = 0) {
  svg.querySelectorAll('circle[stroke-dasharray]').forEach((c, i) => {
    const target = c.getAttribute('stroke-dasharray');
    const C = target.split(' ')[1];
    c.style.transition = 'none';
    c.setAttribute('stroke-dasharray', `0 ${C}`);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      c.style.transition = `stroke-dasharray 1s cubic-bezier(.4,0,.2,1) ${delay + i * 90}ms`;
      c.setAttribute('stroke-dasharray', target);
    }));
  });
}

// 进度条宽度动画（data-w 目标百分比）
function animateBars(root) {
  root.querySelectorAll('[data-w]').forEach((b, i) => {
    b.style.width = '0%';
    b.style.transition = `width 1s cubic-bezier(.4,0,.2,1) ${200 + i * 120}ms`;
    requestAnimationFrame(() => requestAnimationFrame(() => { b.style.width = b.dataset.w; }));
  });
}

// 滚动显现（IntersectionObserver）
function revealOnScroll(selector = '.reveal', cb) {
  const io = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (en.isIntersecting) {
        en.target.classList.add('in');
        if (cb) cb(en.target);
        io.unobserve(en.target);
      }
    });
  }, { threshold: 0.18 });
  document.querySelectorAll(selector).forEach((el) => io.observe(el));
  return io;
}

// 迷你 sparkline
function spark(container, values, color, w = 120, h = 36) {
  const max = Math.max(...values), min = Math.min(...values);
  const X = (i) => (i / (values.length - 1)) * (w - 4) + 2;
  const Y = (v) => h - 4 - ((v - min) / (max - min || 1)) * (h - 8);
  let d = '';
  values.forEach((v, i) => { d += (i ? ' L' : 'M') + X(i).toFixed(1) + ',' + Y(v).toFixed(1); });
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('width', '100%');
  svg.setAttribute('height', h);
  svg.style.overflow = 'visible';
  const area = document.createElementNS(ns, 'path');
  area.setAttribute('d', d + ` L${X(values.length - 1)},${h} L${X(0)},${h} Z`);
  area.setAttribute('fill', color); area.setAttribute('opacity', '.12');
  const line = document.createElementNS(ns, 'path');
  line.setAttribute('d', d); line.setAttribute('fill', 'none');
  line.setAttribute('stroke', color); line.setAttribute('stroke-width', '1.8');
  line.setAttribute('stroke-linecap', 'round');
  svg.append(area, line);
  container.appendChild(svg);
  return svg;
}

// 通用入场 CSS（注入一次）
(function injectMotionCSS() {
  const css = `
  .stagger > * { opacity: 0; transform: translateY(14px); animation: m-rise .6s cubic-bezier(.2,.7,.3,1) forwards; animation-delay: calc(var(--i) * 60ms); }
  @keyframes m-rise { to { opacity: 1; transform: none; } }
  .reveal { opacity: 0; transform: translateY(26px); transition: opacity .7s ease, transform .7s cubic-bezier(.2,.7,.3,1); }
  .reveal.in { opacity: 1; transform: none; }
  @media (prefers-reduced-motion: reduce) {
    .stagger > *, .reveal { animation: none !important; transition: none !important; opacity: 1 !important; transform: none !important; }
  }`;
  const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s);
})();