const currency0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const currency2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
const number0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const number1 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export const fmtMoney = (v: number | null | undefined, cents = false) =>
  isNum(v) ? (cents ? currency2 : currency0).format(v) : "—";
export const fmtMoneyCompact = (v: number | null | undefined) => (isNum(v) ? `$${compact.format(v)}` : "—");
export const fmtNumber = (v: number | null | undefined, decimals = 0) =>
  isNum(v) ? (decimals ? number1 : number0).format(v) : "—";
export const fmtCompact = (v: number | null | undefined) => (isNum(v) ? compact.format(v) : "—");
export const fmtPct = (v: number | null | undefined, decimals = 1) => (isNum(v) ? `${(v * 100).toFixed(decimals)}%` : "—");
export const fmtChange = (v: number | null | undefined, decimals = 1) =>
  isNum(v) ? `${v > 0 ? "+" : ""}${(v * 100).toFixed(decimals)}%` : "—";

/** Dates from the API are ISO strings; parse date-only values as local calendar dates. */
export function parseDate(s: string): Date {
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? new Date(`${s}T00:00:00`) : new Date(s);
}
export const fmtDate = (
  s: string | null | undefined,
  opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", year: "numeric" },
) => (s ? parseDate(s).toLocaleDateString("en-US", opts) : "—");
export const fmtShortDate = (s: string | null | undefined) => fmtDate(s, { month: "short", day: "numeric" });
export const fmtDateTime = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "2-digit",
                                            minute: "2-digit" }) : "—";

export function isoDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
export function addDays(iso: string, days: number): string {
  const d = parseDate(iso);
  d.setDate(d.getDate() + days);
  return isoDate(d);
}

export const titleCase = (s: string) => s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

/** Client-side CSV for tables already on screen. */
export function toCsv(rows: Record<string, unknown>[], columns?: string[]): string {
  const cols = columns ?? (rows[0] ? Object.keys(rows[0]) : []);
  const esc = (v: unknown) => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

export function downloadText(filename: string, text: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
