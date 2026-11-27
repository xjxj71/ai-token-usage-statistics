// Shared mock data + tiny SVG chart helpers for the theme prototypes.
// Self-contained, no dependencies. Each theme page includes this inline.
const ICONS = [
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12l7 7 7-7"/></svg>',
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18h6M10 22h4M12 2a7 7 0 00-4 12.7c.6.5 1 1.4 1 2.3h6c0-.9.4-1.8 1-2.3A7 7 0 0012 2z"/></svg>',
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M3 9h18"/></svg>',
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>',
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
];
const AGENTS = [
  { name: 'claude-code', tokens: 15200000, cost: 986 },
  { name: 'zcode',       tokens: 12400000, cost: 742 },
  { name: 'codex',       tokens: 6800000,  cost: 398 },
  { name: 'qoder',       tokens: 4200000,  cost: 214 },
  { name: 'hermes',      tokens: 2900000,  cost: 98  },
  { name: 'openclaw',    tokens: 1300000,  cost: 48  },
];
const MODELS = [
  { name: 'glm-5.4', tokens: 16800000 },
  { name: 'glm-5.3', tokens: 11200000 },
  { name: 'gpt-5.1-codex', tokens: 6800000 },
  { name: 'qwen3-max', tokens: 4200000 },
  { name: 'mimo-v2.6-pro', tokens: 2900000 },
  { name: 'claude-sonnet-4.5', tokens: 900000 },
];
const STATS = [
  { title: '总 Token', value: '42.8M', trend: 12.4, goodWhenDown: false },
  { title: '输入 Token', value: '35.6M', trend: 9.1, goodWhenDown: false },
  { title: '输出 Token', value: '4.9M', trend: 18.2, goodWhenDown: false },
  { title: '思考 Token', value: '2.3M', trend: 22.6, goodWhenDown: false },
  { title: '缓存 Token', value: '31.2M', trend: 7.8, goodWhenDown: false },
  { title: '总费用', value: '¥2,486', trend: -6.3, goodWhenDown: true },
  { title: '请求次数', value: '18,432', trend: 11.0, goodWhenDown: false },
  { title: '缓存命中率', value: '87.6%', trend: 2.1, goodWhenDown: false },
];
const USAGE_ROWS = [
  ['11-28 09:41', 'zcode', 'glm-5.4', 'ai-token-usage', '182K', '9.4K', '4.1K', '¥0.86'],
  ['11-28 09:38', 'claude-code', 'claude-sonnet-4.5', 'research', '96K', '12.2K', '6.8K', '¥1.42'],
  ['11-28 09:32', 'codex', 'gpt-5.1-codex', 'ai-token-usage', '143K', '7.1K', '3.2K', '¥0.71'],
  ['11-28 09:27', 'qoder', 'qwen3-max', 'portal', '88K', '5.6K', '—', '¥0.33'],
  ['11-28 09:19', 'hermes', 'glm-5.3', 'wsl-dev', '64K', '3.9K', '1.8K', '¥0.21'],
  ['11-28 09:12', 'openclaw', 'mimo-v2.6-pro', 'sandbox', '41K', '2.2K', '—', '¥0.09'],
];

// deterministic pseudo-random so charts look organic but stable
function rng(seed) { let s = seed; return () => (s = (s * 9301 + 49297) % 233280) / 233280; }
function trendSeries(n, base, vol, seed) {
  const r = rng(seed); const out = []; let v = base;
  for (let i = 0; i < n; i++) { v = Math.max(base * 0.3, v + (r() - 0.45) * vol); out.push(v); }
  return out;
}
function fmt(n) {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K';
  return String(Math.round(n));
}
function el(tag, attrs, children) {
  const ns = 'http://www.w3.org/2000/svg';
  const e = document.createElementNS(ns, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  (children || []).forEach(c => e.appendChild(c));
  return e;
}
function txt(x, y, str, attrs) {
  const t = el('text', Object.assign({ x, y }, attrs)); t.textContent = str; return t;
}

// Multi-series smooth area+line chart. colors: array. Returns SVG.
function lineChart(container, seriesList, colors, opts = {}) {
  const W = opts.w || 720, H = opts.h || 260, padL = 44, padR = 14, padT = 16, padB = 28;
  const n = seriesList[0].length;
  const max = Math.max(...seriesList.flat()) * 1.12;
  const iw = W - padL - padR, ih = H - padT - padB;
  const X = i => padL + (i / (n - 1)) * iw;
  const Y = v => padT + ih - (v / max) * ih;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', preserveAspectRatio: 'none', class: 'chart' });
  const gridC = opts.grid || 'rgba(128,128,128,.14)';
  const labelC = opts.label || 'rgba(128,128,128,.75)';
  for (let g = 0; g <= 4; g++) {
    const y = padT + (g / 4) * ih;
    svg.appendChild(el('line', { x1: padL, y1: y, x2: W - padR, y2: y, stroke: gridC, 'stroke-width': 1 }));
    svg.appendChild(txt(padL - 8, y + 3, fmt(max * (1 - g / 4)), { 'text-anchor': 'end', 'font-size': 10, fill: labelC }));
  }
  const days = ['10-29', '11-04', '11-10', '11-16', '11-22', '11-28'];
  days.forEach((d, i) => svg.appendChild(txt(padL + (i / (days.length - 1)) * iw, H - 8, d, { 'text-anchor': 'middle', 'font-size': 10, fill: labelC })));
  seriesList.forEach((s, si) => {
    const c = colors[si % colors.length];
    let d = '';
    s.forEach((v, i) => {
      const x = X(i), y = Y(v);
      if (i === 0) d += `M${x},${y}`;
      else { const px = X(i - 1), py = Y(s[i - 1]); const cx = (px + x) / 2; d += ` C${cx},${py} ${cx},${y} ${x},${y}`; }
    });
    const gid = 'grad' + si + Math.random().toString(36).slice(2, 7);
    const defs = el('defs', {}, [el('linearGradient', { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, [
      el('stop', { offset: '0%', 'stop-color': c, 'stop-opacity': opts.fillOpacity ?? 0.28 }),
      el('stop', { offset: '100%', 'stop-color': c, 'stop-opacity': 0 }),
    ])]);
    svg.appendChild(defs);
    svg.appendChild(el('path', { d: d + ` L${X(n - 1)},${padT + ih} L${X(0)},${padT + ih} Z`, fill: `url(#${gid})`, stroke: 'none' }));
    svg.appendChild(el('path', { d, fill: 'none', stroke: c, 'stroke-width': opts.stroke || 2, 'stroke-linecap': 'round' }));
  });
  container.appendChild(svg);
}

function donut(container, data, colors, opts = {}) {
  const size = opts.size || 200, r = size / 2 - 14, cx = size / 2, cy = size / 2;
  const total = data.reduce((a, b) => a + b.value, 0);
  const svg = el('svg', { viewBox: `0 0 ${size} ${size}`, width: size, height: size, class: 'chart' });
  let ang = -90;
  const C = 2 * Math.PI * r;
  data.forEach((d, i) => {
    const frac = d.value / total;
    const circle = el('circle', {
      cx, cy, r, fill: 'none', stroke: colors[i % colors.length],
      'stroke-width': opts.thickness || 22,
      'stroke-dasharray': `${frac * C} ${C}`,
      'stroke-dashoffset': 0,
      transform: `rotate(${ang} ${cx} ${cy})`,
      'stroke-linecap': 'butt',
    });
    svg.appendChild(circle);
    ang += frac * 360;
  });
  svg.appendChild(txt(cx, cy - 2, fmt(total), { 'text-anchor': 'middle', 'font-size': 22, 'font-weight': 700, fill: opts.centerColor || 'currentColor' }));
  svg.appendChild(txt(cx, cy + 16, '总 Token', { 'text-anchor': 'middle', 'font-size': 11, fill: opts.subColor || 'rgba(128,128,128,.8)' }));
  container.appendChild(svg);
}

function hbars(container, data, colors, opts = {}) {
  const max = Math.max(...data.map(d => d.value));
  data.forEach((d, i) => {
    const row = document.createElement('div'); row.className = 'hbar-row';
    const label = document.createElement('span'); label.className = 'hbar-label'; label.textContent = d.name;
    const track = document.createElement('div'); track.className = 'hbar-track';
    const fill = document.createElement('div'); fill.className = 'hbar-fill';
    fill.style.width = (d.value / max * 100) + '%';
    fill.style.background = colors[i % colors.length];
    track.appendChild(fill);
    const val = document.createElement('span'); val.className = 'hbar-val'; val.textContent = fmt(d.value);
    row.append(label, track, val);
    container.appendChild(row);
  });
}

// Render the common dashboard blocks into a page. `P` supplies palette + hooks.
function renderDashboard(P) {
  // stat cards
  const statWrap = document.getElementById('stats');
  STATS.forEach((s, i) => {
    const card = document.createElement('div'); card.className = 'stat-card';
    const up = s.trend > 0; const good = s.goodWhenDown ? !up : up;
    const arrow = up ? '↑' : '↓';
    card.innerHTML = `
      <div class="stat-top"><span class="stat-ico" style="color:${P.accents[i % P.accents.length]}">${P.icons[i % P.icons.length]}</span><span class="stat-title">${s.title}</span></div>
      <div class="stat-value">${s.value}</div>
      <div class="stat-trend ${good ? 'good' : 'bad'}">${arrow} ${Math.abs(s.trend).toFixed(1)}% <span class="stat-trend-label">较上期</span></div>`;
    statWrap.appendChild(card);
  });
  // filter chips
  const chips = document.getElementById('chips');
  AGENTS.forEach((a, i) => {
    const c = document.createElement('button'); c.className = 'chip' + (i < 2 ? ' active' : '');
    c.innerHTML = `<span class="chip-dot" style="background:${P.agentColors[i]}"></span>${a.name}`;
    chips.appendChild(c);
  });
  // trend
  const tl = document.getElementById('trend');
  const s1 = trendSeries(30, 900, 260, 7), s2 = trendSeries(30, 620, 200, 21), s3 = trendSeries(30, 380, 150, 42);
  lineChart(tl, [s1, s2, s3], P.series, { grid: P.grid, label: P.axis, fillOpacity: P.fillOpacity, stroke: P.stroke });
  // donut
  donut(document.getElementById('donut'), AGENTS.map(a => ({ name: a.name, value: a.tokens })), P.agentColors, { centerColor: P.text, subColor: P.axis, thickness: P.donutThickness });
  const legend = document.getElementById('donut-legend');
  const total = AGENTS.reduce((a, b) => a + b.tokens, 0);
  AGENTS.forEach((a, i) => {
    const li = document.createElement('div'); li.className = 'legend-item';
    li.innerHTML = `<span class="legend-dot" style="background:${P.agentColors[i]}"></span><span class="legend-name">${a.name}</span><span class="legend-val">${(a.tokens / total * 100).toFixed(0)}%</span>`;
    legend.appendChild(li);
  });
  // model bars
  hbars(document.getElementById('modelbars'), MODELS.map(m => ({ name: m.name, value: m.tokens })), P.series.concat(P.agentColors), {});
  // usage table
  const tb = document.getElementById('usage-body');
  USAGE_ROWS.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = r.map((c, i) => `<td class="${i === 1 ? 'agent-cell' : ''}">${c}</td>`).join('');
    tb.appendChild(tr);
  });
}