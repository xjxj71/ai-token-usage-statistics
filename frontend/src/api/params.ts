/** Shared helpers to turn FilterState into /api query params. */

import type { FilterState, TimeRange } from "../types";

export function localDateStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function computeFromTo(range: TimeRange): { from?: string; to?: string } {
  if (range === "custom") return {};
  const now = new Date();
  const to = localDateStr(now);
  let from: string;
  switch (range) {
    case "today":
      from = to;
      break;
    case "7d": {
      const d = new Date(now);
      d.setDate(d.getDate() - 7);
      from = localDateStr(d);
      break;
    }
    case "30d": {
      const d = new Date(now);
      d.setDate(d.getDate() - 30);
      from = localDateStr(d);
      break;
    }
    default:
      from = to;
  }
  return { from, to };
}

export function buildParams(filter: FilterState): Record<string, string> {
  const p: Record<string, string> = { range: filter.range };
  const { from, to } = computeFromTo(filter.range);
  if (filter.range === "custom" && filter.from) {
    p.from = filter.from;
  } else if (from) {
    p.from = from;
  }
  if (filter.range === "custom" && filter.to) {
    p.to = filter.to;
  } else if (to) {
    p.to = to;
  }
  if (filter.agents.length > 0) p.agent = filter.agents.join(",");
  if (filter.models.length > 0) p.model = filter.models.join(",");
  if (filter.projects.length > 0) p.project = filter.projects.join(",");
  return p;
}
