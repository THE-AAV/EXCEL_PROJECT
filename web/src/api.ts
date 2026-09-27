// Small wrapper around fetch: sends the session cookie and the header the backend requires for changes.
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Params = Record<string, string | string[] | undefined | null>;

export function query(params: Params): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v == null || v === "") continue;
    for (const item of Array.isArray(v) ? v : [v]) q.append(k, item);
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Requested-With", "fetch");
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  const res = await fetch(`/api${path}`, { ...init, headers, body, credentials: "same-origin" });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message = typeof data.detail === "string" ? data.detail : Array.isArray(data.detail)
        ? data.detail.map((d: { msg: string }) => d.msg).join("; ") : message;
    } catch {
      /* not JSON */
    }
    if (res.status === 401) window.dispatchEvent(new Event("signed-out"));
    throw new ApiError(res.status, message);
  }
  const type = res.headers.get("Content-Type") ?? "";
  return (type.includes("application/json") ? res.json() : res.blob()) as Promise<T>;
}

export async function download(path: string, fallbackName: string) {
  const res = await fetch(`/api${path}`, { credentials: "same-origin" });
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  const cd = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="?([^"]+)"?/.exec(cd)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export type Role = "admin" | "editor" | "viewer";
export interface User {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  active?: boolean;
  locked?: boolean;
  created_at?: string;
  last_login?: string | null;
}

export type Row = Record<string, unknown>;

export interface Reports {
  filters: { as_of: string; date_from: string | null; date_to: string | null };
  dashboard: {
    net_sales: number;
    net_profit: number;
    net_margin: number | null;
    gross_profit: number;
    closing_stock_value: number;
    payable: number;
    receivable: number;
    payable_over_90: number;
    receivable_over_90: number;
    purchase_bills: number;
    sales_bills: number;
    data_checks: number;
    products_without_purchase: string[];
  };
  pnl: Row[];
  stock: Row[];
  creditors: { summary: Row[]; bills: Row[] };
  debtors: { summary: Row[]; bills: Row[] };
  open_orders: Row[];
  po: Row[];
  so: Row[];
  debit_notes: Row[];
  credit_notes: Row[];
  margins: Row[];
  checks: Row[];
  age_buckets: string[];
}

export interface Status {
  has_data: boolean;
  source: { filename: string; loaded_at: string } | null;
  options: {
    types: string[];
    sub_types: string[];
    companies: string[];
    products: string[];
    min_date: string | null;
    max_date: string | null;
  };
}
