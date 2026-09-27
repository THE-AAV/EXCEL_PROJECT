const money = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const money2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const num = (v: unknown) => (typeof v === "number" && isFinite(v) ? v : null);

export const inr = (v: unknown) => (num(v) == null ? "" : money.format(num(v)!));
export const rate = (v: unknown) => (num(v) == null ? "" : money2.format(num(v)!));
export const pct = (v: unknown) => (num(v) == null ? "" : `${(num(v)! * 100).toFixed(1)}%`);

/** 12,34,567 -> "12.35 L", 1,23,45,678 -> "1.23 Cr" */
export function short(v: unknown): string {
  const n = num(v);
  if (n == null) return "–";
  const a = Math.abs(n);
  if (a >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${money.format(n)}`;
}

export function day(v: unknown): string {
  if (typeof v !== "string" || !v) return "";
  const d = new Date(v.length === 10 ? `${v}T00:00:00` : v);
  if (isNaN(d.getTime())) return v;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function when(v: unknown): string {
  if (typeof v !== "string" || !v) return "";
  const d = new Date(v.endsWith("Z") || v.includes("+") ? v : `${v}Z`);
  return isNaN(d.getTime()) ? v : d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

export function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
