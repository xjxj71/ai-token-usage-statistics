/** CSV field escaping with spreadsheet formula-injection neutralization. */
export function csvEscape(value: unknown): string {
  let s = value === null || value === undefined ? "" : String(value);
  // Neutralize formula injection when opened in Excel/Sheets.
  if (/^[=+\-@\t\r]/.test(s)) {
    s = `'${s}`;
  }
  return `"${s.replace(/"/g, '""')}"`;
}
