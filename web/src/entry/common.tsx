import { useId, type ReactNode } from "react";
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

/** Pick a name from the list, or type a new one (the list suggests as you type). */
export function Combo({ value, onChange, options, placeholder }: {
  value: string; onChange: (v: string) => void; options: string[]; placeholder?: string;
}) {
  const id = useId();
  const isNew = value.trim() !== "" && !options.some((o) => key(o) === key(value));
  return (
    <span className="combo">
      <input list={id} value={value} placeholder={placeholder ?? "Choose, or type a new one"}
        onChange={(e) => onChange(e.target.value)} />
      <datalist id={id}>{options.map((o) => <option key={o} value={o} />)}</datalist>
      {isNew && <span className="new-tag" title="Not in the data yet: it is added with this entry">new</span>}
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
