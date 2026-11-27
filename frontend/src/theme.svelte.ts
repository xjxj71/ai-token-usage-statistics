// 主题系统：所有颜色定义在 app.css 的 CSS 变量里（:root = classic，
// [data-theme=...] 覆盖），这里只负责切换、持久化，以及给 ECharts 提供
// 运行时调色板（ECharts 不认识 var(--x)，需要从 computed style 取值）。
// chartPalette()/agentColor() 内部读取 themeState.current，因此在 $effect
// 或模板中调用它们会随主题切换自动重算。

export type ThemeId = "classic" | "obsidian" | "daylight" | "amber" | "neon";

export const THEME_LIST: { id: ThemeId; label: string; hint: string; dot: string }[] = [
  { id: "classic", label: "经典深色", hint: "当前默认 · 靛蓝石板", dot: "#6366F1" },
  { id: "obsidian", label: "曜石 Obsidian", hint: "石墨玻璃 · 青紫点缀", dot: "#22D3EE" },
  { id: "daylight", label: "晨雾 Daylight", hint: "浅色清爽 · 柔和阴影", dot: "#5B5BD6" },
  { id: "amber", label: "暖砂 Warm Sand", hint: "暖纸编辑风 · 莫兰迪", dot: "#C2571B" },
  { id: "neon", label: "霓虹 Neon", hint: "赛博光效 · 等宽数字", dot: "#FF2E97" },
];

const STORAGE_KEY = "token-stat-theme";
const VALID = new Set(THEME_LIST.map((t) => t.id));

function initialTheme(): ThemeId {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && VALID.has(saved as ThemeId)) return saved as ThemeId;
  } catch {
    // localStorage 不可用时退回默认
  }
  return "classic";
}

export const themeState = $state({ current: initialTheme() });

export function setTheme(id: ThemeId) {
  document.documentElement.dataset.theme = id;
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // 忽略持久化失败
  }
  themeState.current = id;
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export interface ChartPalette {
  series: string[];
  text: string;
  text2: string;
  text3: string;
  axis: string;
  split: string;
  card: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  barFrom: string;
  barTo: string;
  projectFrom: string;
  projectTo: string;
  stackInput: string;
  stackOutput: string;
  stackCache: string;
}

/** 在 $effect / 模板中调用，主题切换时自动触发重算 */
export function chartPalette(): ChartPalette {
  void themeState.current;
  return {
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => cssVar(`--chart-${i}`)),
    text: cssVar("--text"),
    text2: cssVar("--text-2"),
    text3: cssVar("--text-3"),
    axis: cssVar("--border"),
    split: `rgba(${cssVar("--border-rgb")},.5)`,
    card: cssVar("--card"),
    tooltipBg: cssVar("--card"),
    tooltipBorder: cssVar("--border"),
    tooltipText: cssVar("--text"),
    barFrom: cssVar("--bar-from"),
    barTo: cssVar("--bar-to"),
    projectFrom: cssVar("--project-from"),
    projectTo: cssVar("--project-to"),
    stackInput: cssVar("--chart-1"),
    stackOutput: cssVar("--chart-2"),
    stackCache: cssVar("--chart-4"),
  };
}

/** Agent 身份色（FilterBar 圆点、表格徽章、环形图共用） */
export function agentColor(agent: string): string {
  void themeState.current;
  return cssVar(`--agent-${agent}`) || cssVar("--chart-1");
}

/** 表格徽章：底色取身份色 16% 透明，文字色向当前主题文字色混合 28%
 * （深色主题自动提亮、浅色主题自动加深，保证对比度） */
export function agentBadge(agent: string): { bg: string; text: string } {
  const c = agentColor(agent);
  return {
    bg: `color-mix(in srgb, ${c} 16%, transparent)`,
    text: `color-mix(in srgb, ${c} 72%, ${cssVar("--text")})`,
  };
}