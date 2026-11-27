// 全局 UI 状态：当前视图 + 侧栏折叠。
// 视图 keep-alive：所有视图常驻 DOM，切换只改 hidden，图表不重建（修切换卡顿）。
// 图表组件在 $effect 里读取 uiState.view，视图显示时补初始化 / resize。

export type ViewId = "overview" | "trends" | "sessions" | "records" | "monitor" | "pricing" | "data";

const VIEWS: ViewId[] = ["overview", "trends", "sessions", "records", "monitor", "pricing", "data"];
const VIEW_KEY = "token-stat-view";
const COLLAPSE_KEY = "token-stat-sidebar-collapsed";

function loadView(): ViewId {
  try {
    const v = localStorage.getItem(VIEW_KEY) as ViewId;
    if (v && VIEWS.includes(v)) return v;
  } catch {
    // ignore
  }
  return "overview";
}

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

export const uiState = $state({ view: loadView(), collapsed: loadCollapsed() });

export function setView(v: ViewId) {
  uiState.view = v;
  try {
    localStorage.setItem(VIEW_KEY, v);
  } catch {
    // ignore
  }
}

export function toggleCollapsed() {
  uiState.collapsed = !uiState.collapsed;
  try {
    localStorage.setItem(COLLAPSE_KEY, uiState.collapsed ? "1" : "0");
  } catch {
    // ignore
  }
}