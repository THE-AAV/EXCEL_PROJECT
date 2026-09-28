import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { rate as fmtRate } from "../format";

export type Side = "Purchase" | "Sales";
export type Rec = Record<string, string | number | null>;

export interface EntryContext {
  version: string;
  lists: Record<string, string[]>;
  party_defaults: Record<Side, Record<string, Record<string, string>>>;
  hsn: Record<string, string>;
  orders: Record<"PO" | "SO", Rec[]>;
  all_contracts: Record<"PO" | "SO", (string | number)[]>;
  next: { PO: string | number; SO: string | number; Purchase: string; Sales: string; sales_bill: string | number };
  bills: Record<Side, Rec[]>;
  outstanding: Record<Side, { row: number; party: string; bill_no: string | null; bill_date: string | null;
    days: number | null; outstanding: number }[]>;
  notes: Record<Side, Rec[]>;
  note_numbers: Record<Side, string[]>;
  expense_fields: Record<Side, Record<string, string[]>>;
  pre_bill_fields: string[];
}

export interface FormProps {
  ctx: EntryContext;
  save: (action: string, body: object) => Promise<boolean>;
  busy: boolean;
}

export const LABELS: Record<string, string> = {
  adhat: "Adhat", amc: "AMC", labour: "Labour", transport_pre: "Transportation", wh_load: "WH Load", bags: "Bags",
  other_pre: "Other", discount: "Discount", vatav: "Vatav", storage: "Storage", brokerage: "Brokerage",
  sampling: "Sampling", repacking: "Repacking", transport_post: "Transportation", loading: "Loading / Unloading",
};

export const key = (v: unknown) => String(v ?? "").trim().replace(/\s+/g, " ").toLowerCase();
export const num = (v: unknown) => {
  const n = typeof v === "number" ? v : parseFloat(String(v ?? "").replace(/,/g, ""));
  return isFinite(n) ? n : 0;
};
export const round2 = (v: number) => Math.round(v * 100) / 100;

/** Label above an input, like the rest of the app. */
export function Field({ label, required, hint, children, wide }: {
  label: string; required?: boolean; hint?: string; children: ReactNode; wide?: boolean;
}) {
  return (
    <label className={`field ${wide ? "wide" : ""}`}>
      <span className="field-label">{label}{required && <b className="req"> *</b>}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

/** What each list holds, for "+ Add a new …". */
export const NOUN: Record<string, string> = {
  "party:Purchase": "party", "party:Sales": "party", product: "product", broker: "broker", company: "company",
  warehouse: "warehouse", type: "type", sub_type: "sub type", branch: "branch", place: "delivery place",
  packing: "packing", reason: "reason", expense: "expense",
};

/** Names added while entering (before they are saved), so every dropdown on the page offers them. */
export const AddedNames = createContext<{ added: Record<string, string[]>; add: (list: string, name: string) => void }>({
  added: {}, add: () => undefined,
});

export function useAddedNames() {
  const [added, setAdded] = useState<Record<string, string[]>>(() => {
    try { return JSON.parse(sessionStorage.getItem("added-names") || "{}"); } catch { return {}; }
  });
  const add = useCallback((list: string, name: string) => {
    setAdded((a) => {
      if ((a[list] ?? []).some((x) => key(x) === key(name))) return a;
      const next = { ...a, [list]: [...(a[list] ?? []), name.trim().replace(/\s+/g, " ")] };
      try { sessionStorage.setItem("added-names", JSON.stringify(next)); } catch { /* private window */ }
      return next;
    });
  }, []);
  return { added, add };
}

/** The lists with the names added on this page (saved names already come back from the data). */
export function withAdded(lists: Record<string, string[]>, added: Record<string, string[]>) {
  const out = { ...lists };
  for (const [list, names] of Object.entries(added)) {
    const have = new Set((lists[list] ?? []).map(key));
    const extra = names.filter((n) => !have.has(key(n)));
    if (extra.length) out[list] = [...(lists[list] ?? []), ...extra].sort((a, b) => a.localeCompare(b));
  }
  return out;
}

/** A dropdown that suggests as you type. With a list name it also offers "+ Add new" (not in strict mode, where only
 * the choices shown can be picked, e.g. a bill). Works the same in a form and in a table cell. */
export function Combo({ value, onChange, options, placeholder, list, strict, cell, invalid }: {
  value: string; onChange: (v: string) => void; options: string[]; placeholder?: string; list?: string;
  strict?: boolean; cell?: boolean; invalid?: boolean;
}) {
  const { added, add } = useContext(AddedNames);
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState<string | null>(null);   // what is typed; null = showing the whole list
  const [hi, setHi] = useState(0);
  const [adding, setAdding] = useState(false);
  const [box, setBox] = useState<{ left: number; top: number; width: number; up: boolean } | null>(null);
  const noun = (list && NOUN[list]) || "name";
  const known = options.some((o) => key(o) === key(value));
  const isAdded = !!list && (added[list] ?? []).some((x) => key(x) === key(value));
  const isNew = !strict && value.trim() !== "" && (!known || isAdded);
  const q = key(typed ?? "");
  const shown = (q ? options.filter((o) => key(o).includes(q)) : options).slice(0, 80);
  const canAdd = !strict && !!list;
  const exact = q !== "" && options.some((o) => key(o) === q);
  type Item = { label: string; value: string; add?: boolean; start?: boolean };
  const items: Item[] = adding && !q ? [] : [
    ...(canAdd && !q ? [{ label: `+ Add a new ${noun}…`, value: "", start: true }] : []),
    ...shown.map((o) => ({ label: o, value: o })),
    ...(canAdd && q && !exact ? [{ label: `+ Add “${(typed ?? "").trim()}” as a new ${noun}`, value: (typed ?? "").trim(), add: true }] : []),
  ];

  const place = () => {
    const r = input.current?.getBoundingClientRect();
    if (!r) return;
    const up = r.bottom + 260 > window.innerHeight && r.top > 260;
    setBox({ left: r.left, top: up ? r.top : r.bottom, width: Math.max(r.width, 220), up });
  };
  const show = () => { place(); setOpen(true); };
  const close = () => { setOpen(false); setTyped(null); setAdding(false); setHi(0); };
  useEffect(() => {
    if (!open) return;
    const off = () => close();
    window.addEventListener("scroll", off, true);
    window.addEventListener("resize", off);
    return () => { window.removeEventListener("scroll", off, true); window.removeEventListener("resize", off); };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const choose = (it: Item) => {
    if (it.start) { setAdding(true); setTyped(""); onChange(""); input.current?.focus(); return; }
    if (it.add && list) add(list, it.value);
    onChange(it.value);
    close();
  };
  const leave = () => {
    // typed but not picked: keep it (a new name) or, in strict mode, the one choice it matches
    if (typed !== null && typed.trim() !== "") {
      const t = typed.trim();
      const match = options.find((o) => key(o) === key(t)) ?? (strict ? shown.length === 1 ? shown[0] : "" : undefined);
      if (match !== undefined) onChange(match);
      else { if (canAdd && list) add(list, t); onChange(t); }
    }
    close();
  };

  return (
    <span className={`combo ${cell ? "in-cell" : ""}`}>
      <input ref={input} value={typed ?? value} className={invalid || (strict && value && !known) ? "invalid" : ""}
        placeholder={adding ? `Type the new ${noun}` : placeholder ?? (strict ? "Choose…" : "Choose, or type a new one")}
        onFocus={show} onClick={show} onBlur={leave}
        onChange={(e) => { setTyped(e.target.value); setHi(0); if (!open) show(); if (!strict) onChange(e.target.value); }}
        onKeyDown={(e) => {
          if (!open) { if (e.key === "ArrowDown") { show(); e.preventDefault(); } return; }
          if (e.key === "ArrowDown") { setHi((h) => Math.min(h + 1, items.length - 1)); e.preventDefault(); }
          else if (e.key === "ArrowUp") { setHi((h) => Math.max(h - 1, 0)); e.preventDefault(); }
          else if (e.key === "Enter") {
            const it = items[hi];
            if (it && (typed !== null || it.start)) { choose(it); e.preventDefault(); e.stopPropagation(); }
            else leave();
          } else if (e.key === "Escape") { close(); e.stopPropagation(); }
        }} />
      <span className="combo-arrow" aria-hidden onMouseDown={(e) => { e.preventDefault(); input.current?.focus(); show(); }}>▾</span>
      {isNew && <span className="new-tag" title="Not in the data yet: it is added with this entry">new</span>}
      {open && box && (
        <ul className={`combo-list ${box.up ? "up" : ""}`} style={{ left: box.left, width: box.width,
          ...(box.up ? { bottom: window.innerHeight - box.top } : { top: box.top }) }}>
          {items.length === 0 && <li className="empty">{adding ? `Type the new ${noun}, then press Enter` :
            strict ? "No match" : "No match: keep typing to add it as new"}</li>}
          {items.map((it, i) => (
            <li key={`${i}-${it.label}`} className={`${i === hi ? "hi" : ""} ${it.add || it.start ? "add" : ""}`}
              onMouseDown={(e) => { e.preventDefault(); choose(it); }} onMouseEnter={() => setHi(i)}>{it.label}</li>
          ))}
        </ul>
      )}
    </span>
  );
}

export function Num({ value, onChange, step, placeholder }: {
  value: string; onChange: (v: string) => void; step?: number; placeholder?: string;
}) {
  return <input type="number" inputMode="decimal" min={0} step={step ?? "any"} value={value}
    placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />;
}

/** Automatic next number, or one the person types (checked against those already used). */
export function Numbering({ label, next, used, own, setOwn, auto, setAuto }: {
  label: string; next: string | number; used: (string | number)[]; own: string; setOwn: (v: string) => void;
  auto: boolean; setAuto: (v: boolean) => void;
}) {
  const taken = !auto && own.trim() !== "" && used.some((u) => key(u) === key(own));
  return (
    <Field label={label} hint={auto ? "The next number in the series" : taken ? `${own} is already used` : undefined}>
      <span className="numbering">
        <select value={auto ? "auto" : "own"} onChange={(e) => setAuto(e.target.value === "auto")}>
          <option value="auto">Automatic</option>
          <option value="own">My own</option>
        </select>
        {auto ? <input value={String(next)} disabled /> :
          <input value={own} className={taken ? "invalid" : ""} placeholder={`e.g. ${next}`}
            onChange={(e) => setOwn(e.target.value)} />}
      </span>
    </Field>
  );
}
export const numberingOk = (auto: boolean, own: string, used: (string | number)[]) =>
  auto || (own.trim() !== "" && !used.some((u) => key(u) === key(own)));

export function Preview({ children }: { children: ReactNode }) {
  return <div className="preview">{children}</div>;
}

export const money2 = (v: number) => `₹ ${fmtRate(v)}`;

export function partyDefaults(ctx: EntryContext, side: Side, party: string) {
  return ctx.party_defaults[side][key(party)] ?? {};
}
