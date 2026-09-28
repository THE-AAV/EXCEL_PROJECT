/* "Table (like Excel)" entry style: type many rows into a grid and save them together, as in the Streamlit app.
 * All rows of one save go in together (or none, if any row has a problem), and one Undo takes them all back out. */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { inr, rate as fmtRate, today } from "../format";
import { Combo, key, LABELS, money2, num, partyDefaults, round2, type FormProps, type Rec,
  type Side } from "./common";

type Row = Record<string, string>;
export interface TCol {
  k: string; label: string; type?: "text" | "num" | "date" | "check";
  list?: string; options?: string[]; strict?: boolean;   // a dropdown (list = which names "+ Add new" adds to)
  width?: number; help?: string; readOnly?: boolean; placeholder?: string;
}
interface Item { action: string; label: string; body: object }
interface Built { items: Item[]; preview: Record<string, ReactNode>[]; problems: string[] }

const EMPTY_ROWS = 5;
const blankRows = (cols: TCol[], n = EMPTY_ROWS, start: Row = {}): Row[] =>
  Array.from({ length: n }, () => Object.fromEntries(cols.map((c) => [c.k, start[c.k] ?? ""])));
const filled = (r: Row, ks: string[]) => ks.some((k) => (r[k] ?? "").trim() !== "");
const rowsText = (ns: number[]) => (ns.length === 1 ? `Row ${ns[0]}` : `Rows ${ns.join(", ")}`);

/** A date pasted from Excel (31-03-2026, 31/03/26, 2026-03-31) as the date box wants it. */
function pastedDate(v: string) {
  const t = v.trim();
  if (/^\d{4}-\d{2}-\d{2}/.test(t)) return t.slice(0, 10);
  const m = t.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$/);
  if (!m) return t;
  const y = m[3].length === 2 ? `20${m[3]}` : m[3];
  return `${y}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`;
}

/** The grid itself: one input per cell, Tab / Enter to move, paste a block copied from Excel. */
export function EntryTable({ cols, rows, setRows, fixed, bad }: {
  cols: TCol[]; rows: Row[]; setRows: (f: (rows: Row[]) => Row[]) => void; fixed?: boolean; bad?: Set<number>;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const set = (i: number, k: string, v: string) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const focus = (i: number, c: number) => setTimeout(() => {
    wrap.current?.querySelector<HTMLInputElement>(`[data-cell="${i}-${c}"] input`)?.focus();
  }, 0);

  const paste = (i: number, c: number, e: React.ClipboardEvent) => {
    const text = e.clipboardData.getData("text/plain").replace(/\r/g, "").replace(/\n$/, "");
    if (!/[\t\n]/.test(text)) return;   // one value: the normal paste
    e.preventDefault();
    const block = text.split("\n").map((l) => l.split("\t"));
    setRows((rs) => {
      const out = [...rs];
      while (!fixed && out.length < i + block.length) out.push(blankRows(cols, 1)[0]);
      block.forEach((vals, di) => {
        const r = i + di;
        if (r >= out.length) return;
        const row = { ...out[r] };
        vals.forEach((v, dc) => {
          const col = cols[c + dc];
          if (!col || col.readOnly) return;
          row[col.k] = col.type === "date" ? pastedDate(v) : col.type === "num" ? v.replace(/[,₹\s]/g, "") :
            col.type === "check" ? (/^(1|y|yes|true|✓)$/i.test(v.trim()) ? "1" : "") : v.trim();
        });
        out[r] = row;
      });
      return out;
    });
  };

  const onKey = (i: number, c: number, e: React.KeyboardEvent) => {
    if (e.key !== "Enter" || e.defaultPrevented) return;
    e.preventDefault();
    if (i + 1 >= rows.length) { if (fixed) return; setRows((rs) => [...rs, blankRows(cols, 1)[0]]); }
    focus(i + 1, c);
  };

  return (
    <>
      <div className="sheet-wrap" ref={wrap}>
        <table className="sheet">
          <thead>
            <tr>
              <th className="rowno">#</th>
              {cols.map((c) => <th key={c.k} title={c.help} style={{ minWidth: c.width ?? (c.options ? 170 : 110) }}>
                {c.label}{c.help && <span className="info">ⓘ</span>}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={bad?.has(i + 1) ? "bad" : ""}>
                <td className="rowno">
                  <span>{i + 1}</span>
                  {!fixed && <button className="row-del" title="Remove this row" tabIndex={-1}
                    onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>✕</button>}
                </td>
                {cols.map((c, ci) => (
                  <td key={c.k} data-cell={`${i}-${ci}`} className={c.readOnly ? "ro" : c.type === "num" ? "num" : ""}
                    onPaste={(e) => !c.readOnly && paste(i, ci, e)} onKeyDown={(e) => onKey(i, ci, e)}>
                    {c.readOnly ? <span className="ro-val">{r[c.k]}</span> :
                      c.options ? <Combo cell value={r[c.k] ?? ""} onChange={(v) => set(i, c.k, v)} options={c.options}
                        list={c.list} strict={c.strict} placeholder={c.placeholder ?? ""} /> :
                      c.type === "check" ? <input type="checkbox" checked={r[c.k] === "1"}
                        onChange={(e) => set(i, c.k, e.target.checked ? "1" : "")} /> :
                      <input type={c.type === "date" ? "date" : "text"} inputMode={c.type === "num" ? "decimal" : undefined}
                        value={r[c.k] ?? ""} placeholder={c.placeholder}
                        className={c.type === "num" && r[c.k] && !isFinite(Number(r[c.k].replace(/,/g, ""))) ? "invalid" : ""}
                        onChange={(e) => set(i, c.k, e.target.value)} />}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!fixed && <button className="link" onClick={() => setRows((rs) => [...rs, ...blankRows(cols)])}>+ Add 5 more rows</button>}
    </>
  );
}

/** Grid + what will be saved + problems + the Save button, the same for every step. */
function TableShell({ cols, rows, setRows, reset, built, what, save, busy, intro, fixed }: {
  cols: TCol[]; rows: Row[]; setRows: (f: (rows: Row[]) => Row[]) => void; reset: () => void; built: Built;
  what: [string, string]; save: FormProps["save"]; busy: boolean; intro: ReactNode; fixed?: boolean;
}) {
  const { items, preview, problems } = built;
  const bad = new Set(problems.flatMap((p) => (p.match(/^Rows? ([\d, ]+):/)?.[1] ?? "").split(",").map((x) => parseInt(x))));
  const heads = preview.length ? Object.keys(preview[0]) : [];
  return (
    <>
      <p className="hint">{intro} Click a cell and type, as in Excel. <b>Tab</b> moves right, <b>Enter</b> moves
        down. You can paste a block copied from Excel. Names you don't have yet can be added from any dropdown
        with <b>+ Add new</b>.</p>
      <EntryTable cols={cols} rows={rows} setRows={setRows} fixed={fixed} bad={bad} />
      {preview.length > 0 && (
        <>
          <h3>What will be saved</h3>
          <div className="sheet-wrap">
            <table className="plain wide">
              <thead><tr>{heads.map((h) => <th key={h} className={/₹|kg|MT|Amount|Value|TDS|Total/.test(h) ? "num" : ""}>{h}</th>)}</tr></thead>
              <tbody>{preview.map((p, i) => <tr key={i}>{heads.map((h) =>
                <td key={h} className={typeof p[h] === "number" ? "num" : ""}>{typeof p[h] === "number" ? fmtRate(p[h]) : p[h]}</td>)}</tr>)}</tbody>
            </table>
          </div>
        </>
      )}
      {problems.map((p) => <div key={p} className="notice warn">{p}</div>)}
      <div className="actions">
        <button className="primary" disabled={busy || !items.length || problems.length > 0} onClick={async () => {
          if (await save("batch", { what: items.length === 1 ? what[0] : what[1], items })) reset();
        }}>{items.length ? `Save ${items.length} ${items.length === 1 ? what[0] : what[1]}` : "Save all rows"}</button>
        <button className="secondary" disabled={busy} onClick={reset}>Clear table</button>
        {!items.length && <span className="muted">Nothing to save yet: fill in the table.</span>}
      </div>
    </>
  );
}

function useRows(cols: TCol[], start: Row = {}) {
  const init = () => blankRows(cols, EMPTY_ROWS, start);
  const [rows, setRows] = useState<Row[]>(init);
  return { rows, setRows, reset: () => setRows(init()) };
}

const missing = (r: Row, need: [string, string][]) => need.filter(([k]) => !(r[k] ?? "").trim()).map(([, l]) => l);

// ------------------------------------------------------------------------------------------ ① / ⑥ orders
export function OrderTable({ ctx, save, busy, kind }: FormProps & { kind: "PO" | "SO" }) {
  const side: Side = kind === "PO" ? "Purchase" : "Sales";
  const L = ctx.lists;
  const usual = "Empty = the party's usual";
  const cols: TCol[] = [
    { k: "contract_no", label: "Contract No", placeholder: "automatic", help: "Leave empty to number it automatically" },
    { k: "date", label: "Date", type: "date" },
    { k: "party", label: "Party", options: L[`party:${side}`], list: `party:${side}`, width: 200 },
    { k: "commodity", label: "Product", options: L.product, list: "product" },
    { k: "qty_mt", label: "Qty (MT)", type: "num" },
    { k: "rate", label: "Rate (₹/kg)", type: "num" },
    { k: "broker", label: "Broker", options: L.broker, list: "broker", help: usual },
    { k: "delivery_date", label: "Delivery Date", type: "date" },
    { k: "delivery_place", label: "Delivery Place", options: L.place, list: "place" },
    { k: "packing", label: "Packing", options: L.packing, list: "packing" },
    { k: "company", label: "Company", options: L.company, list: "company", help: usual },
    { k: "warehouse", label: "Warehouse", options: L.warehouse, list: "warehouse", help: usual },
    { k: "branch", label: "Branch", options: L.branch, list: "branch", help: usual },
  ];
  const { rows, setRows, reset } = useRows(cols, { date: today() });
  const built = useMemo<Built>(() => {
    const out: Built = { items: [], preview: [], problems: [] };
    const used = new Set(ctx.all_contracts[kind].map(key));
    rows.forEach((r, i) => {
      if (!filled(r, ["party", "commodity", "qty_mt", "rate"])) return;
      const n = i + 1;
      const miss = missing(r, [["date", "Date"], ["party", "Party"], ["commodity", "Product"]]);
      if (!(num(r.qty_mt) > 0)) miss.push("Qty");
      if (!(num(r.rate) > 0)) miss.push("Rate");
      if (miss.length) out.problems.push(`Row ${n}: fill in ${miss.join(", ")}.`);
      const no = r.contract_no.trim();
      if (no && used.has(key(no))) out.problems.push(`Row ${n}: Contract No. ${no} is already used.`);
      if (no) used.add(key(no));
      const d = partyDefaults(ctx, side, r.party);
      const fields = {
        date: r.date, party: r.party.trim(), commodity: r.commodity.trim(), qty_mt: num(r.qty_mt), rate: num(r.rate),
        broker: r.broker || d.broker || "", delivery_date: r.delivery_date || null, delivery_place: r.delivery_place,
        packing: r.packing, company: r.company || d.company || L.company[0] || "", warehouse: r.warehouse || d.warehouse || "",
        branch: r.branch || d.branch || "",
      };
      out.items.push({ action: "order", label: `Row ${n}`, body: { kind, contract_no: no || null, fields } });
      out.preview.push({ Row: String(n), Contract: no || "(automatic)", Party: fields.party, Product: fields.commodity,
        Broker: fields.broker, Company: fields.company, Warehouse: fields.warehouse, "Value ₹": fields.qty_mt * 1000 * fields.rate });
    });
    return out;
  }, [rows, ctx]); // eslint-disable-line react-hooks/exhaustive-deps
  return <TableShell cols={cols} rows={rows} setRows={setRows} reset={reset} built={built} busy={busy} save={save}
    what={[`${side.toLowerCase()} order`, `${side.toLowerCase()} orders`]} intro={<>One row per contract. Broker, company, warehouse and branch left
    empty are filled in with the party's usual ones.</>} />;
}

// ------------------------------------------------------------------------------------------ ② / ⑦ invoices
const orderLabel = (o: Rec) => `${o.contract_no} · ${o.party} · ${o.commodity} · bal ${num(o.bal_qty_mt)} MT @ ${num(o.rate)}`;
const billLabel = (b: Rec) => `${b.party} · Bill ${b.bill_no ?? "-"} · ${b.commodity ?? ""} · ${b.bill_date ?? "no date"} · row ${b.source_row}`;
const byDateDesc = (a: Rec, b: Rec) => String(b.bill_date ?? "").localeCompare(String(a.bill_date ?? ""));

export function InvoiceTable({ ctx, save, busy, kind }: FormProps & { kind: Side }) {
  const purchase = kind === "Purchase";
  const L = ctx.lists;
  const usual = "Empty = the party's usual";
  const orders = useMemo(() => new Map(ctx.orders[purchase ? "PO" : "SO"].map((o) => [orderLabel(o), o])), [ctx, purchase]);
  const links = useMemo(() => new Map(ctx.bills.Purchase.filter((b) => num(b.qty) > 0).sort(byDateDesc)
    .map((b) => [billLabel(b), b])), [ctx]);
  const stock = purchase ? "WH In Date" : "Delivery Date";
  const cols: TCol[] = [
    { k: "bill_no", label: "Bill No", help: "Rows with the same party, bill no. and date form one bill"
      + (purchase ? "" : ". Leave empty to number it automatically"), placeholder: purchase ? "" : "automatic" },
    { k: "bill_date", label: "Bill Date", type: "date" },
    { k: "party", label: "Party", options: L[`party:${kind}`], list: `party:${kind}`, width: 200, help: "Empty = the contract's party" },
    { k: "commodity", label: "Product", options: L.product, list: "product", help: "Empty = the contract's product" },
    { k: "qty", label: "Weight (kg)", type: "num", help: "Empty = the contract's balance" },
    { k: "rate", label: "Rate (₹/kg)", type: "num", help: "Empty = the contract's rate" },
    { k: "gst", label: "GST %", type: "num", width: 70, help: "Empty = 5% (0% when the type is Import)" },
    { k: "order", label: "Against contract", options: [...orders.keys()], strict: true, width: 300 },
    ...(purchase ? [] : [{ k: "link", label: "Linked purchase bill", options: [...links.keys()], strict: true, width: 320 }]),
    { k: "truck_no", label: "Truck No" },
    { k: "stock_date", label: stock, type: "date", help: "Empty = the bill date" },
    { k: "type", label: "Type", options: L.type, list: "type", help: usual + " (else Local)" },
    { k: "sub_type", label: "Sub Type", options: L.sub_type, list: "sub_type", help: usual },
    { k: "broker", label: "Broker", options: L.broker, list: "broker", help: usual },
    { k: "warehouse", label: "Warehouse", options: L.warehouse, list: "warehouse", help: usual },
    { k: "company", label: "Company", options: L.company, list: "company", help: usual },
    { k: "gstin", label: "Party GSTIN", help: usual },
    { k: "branch", label: "Branch", options: L.branch, list: "branch", help: usual },
    ...(purchase ? ctx.pre_bill_fields.map((f) => ({ k: f, label: LABELS[f] ?? f, type: "num" as const, width: 90,
      help: "Pre-bill expense for this item" })) : []),
  ];
  const { rows, setRows, reset } = useRows(cols, { bill_date: today() });
  const built = useMemo<Built>(() => {
    const out: Built = { items: [], preview: [], problems: [] };
    const groups = new Map<string, { rows: number[]; header: Record<string, string>; lines: Record<string, unknown>[] }>();
    rows.forEach((r, i) => {
      if (!filled(r, ["party", "commodity", "qty", "rate", "order"])) return;
      const n = i + 1;
      const order = r.order ? orders.get(r.order) : undefined;
      const party = r.party.trim() || String(order?.party ?? "");
      const d = partyDefaults(ctx, kind, party);
      const product = r.commodity.trim() || String(order?.commodity ?? "");
      const rate = num(r.rate) || num(order?.rate);
      const qty = num(r.qty) || num(order?.bal_qty_mt) * 1000;
      const type = r.type || d.type || "Local";
      const gst = r.gst.trim() === "" ? (key(type) === "import" ? 0 : 5) : num(r.gst);
      const miss = missing({ ...r, party, commodity: product }, [["bill_date", "Bill Date"], ["party", "Party"], ["commodity", "Product"]]);
      if (!(qty > 0)) miss.push("Weight");
      if (!(rate > 0)) miss.push("Rate");
      if (miss.length) out.problems.push(`Row ${n}: fill in ${miss.join(", ")}.`);
      if (r.order && !order) out.problems.push(`Row ${n}: choose the contract from the list.`);
      const line: Record<string, unknown> = { commodity: product, qty, rate, gst_pct: gst, order_row: order?.source_row ?? null,
        hsn: ctx.hsn[key(product)] ?? null };
      if (purchase) for (const f of ctx.pre_bill_fields) { if (num(r[f])) line[f] = num(r[f]); }
      else if (r.link) {
        const b = links.get(r.link);
        if (b) line.link_row = b.source_row; else out.problems.push(`Row ${n}: choose the purchase bill from the list.`);
      }
      const header: Record<string, string> = {
        party, bill_no: r.bill_no.trim(), bill_date: r.bill_date, stock_date: r.stock_date || r.bill_date, truck_no: r.truck_no,
        type, sub_type: r.sub_type || d.sub_type || "", broker: r.broker || d.broker || "",
        warehouse: r.warehouse || d.warehouse || "", company: r.company || d.company || L.company[0] || "",
        gstin: r.gstin || d.gstin || "", branch: r.branch || d.branch || "",
      };
      const g = `${key(party)}|${r.bill_no.trim() || `auto-${r.bill_date}`}|${r.bill_date}`;
      if (!groups.has(g)) groups.set(g, { rows: [], header: Object.fromEntries(Object.entries(header).filter(([, v]) => v)), lines: [] });
      groups.get(g)!.rows.push(n);
      groups.get(g)!.lines.push(line);
    });
    let next = String(ctx.next.sales_bill ?? "");
    const taken = new Set(ctx.bills[kind].filter((b) => b.bill_no != null).map((b) => key(b.bill_no)));
    for (const g of groups.values()) {
      if (!purchase && !g.header.bill_no) {   // number our own invoices that were left empty
        if (!next) { out.problems.push(`${rowsText(g.rows)}: type the bill no.`); continue; }
        g.header.bill_no = next;
        next = /^\d+$/.test(next) ? String(Number(next) + 1) : "";
      } else if (!purchase && taken.has(key(g.header.bill_no))) {
        out.problems.push(`${rowsText(g.rows)}: bill no. ${g.header.bill_no} is already used in the Sales sheet.`);
      }
      out.items.push({ action: "invoice", label: rowsText(g.rows), body: { kind, header: g.header, lines: g.lines } });
      out.preview.push({ Rows: g.rows.join(", "), Party: g.header.party ?? "", "Bill No": g.header.bill_no ?? "",
        Items: String(g.lines.length), Type: g.header.type ?? "", Broker: g.header.broker ?? "", Company: g.header.company ?? "",
        "Weight (kg)": g.lines.reduce((s, l) => s + num(l.qty), 0),
        "Amount ₹": g.lines.reduce((s, l) => s + num(l.qty) * num(l.rate), 0) });
    }
    return out;
  }, [rows, ctx]); // eslint-disable-line react-hooks/exhaustive-deps
  return <TableShell cols={cols} rows={rows} setRows={setRows} reset={reset} built={built} busy={busy} save={save}
    what={[`${kind.toLowerCase()} bill`, `${kind.toLowerCase()} bills`]} intro={<>One row per item. Rows with the same party, bill no. and date are
    saved as one bill. Details left empty come from the contract and from the party's last bill, as in the form.</>} />;
}

// ------------------------------------------------------------------------------------------ ③ / ⑧ notes
const EXPENSE = "Expense - ";

export function NoteTable({ ctx, save, busy, kind }: FormProps & { kind: Side }) {
  const name = kind === "Purchase" ? "debit note" : "credit note";
  const bills = useMemo(() => new Map([...ctx.bills[kind]].sort(byDateDesc).map((b) => [billLabel(b), b])), [ctx, kind]);
  const types = [...ctx.lists.reason, ...ctx.lists.expense.map((e) => EXPENSE + e)];
  const cols: TCol[] = [
    { k: "note_no", label: "Note No", placeholder: "automatic",
      help: "Rows with the same note no. (or, when empty, the same bill and date) make one note" },
    { k: "date", label: "Date", type: "date" },
    { k: "bill", label: "Bill", options: [...bills.keys()], strict: true, width: 340 },
    { k: "what", label: "Reason / expense", options: types, list: "reason", width: 200,
      help: `A reason (with GST), or one of the "${EXPENSE}…" entries (no GST)` },
    { k: "qty", label: "Qty (kg)", type: "num" },
    { k: "rate", label: "Rate (₹/kg)", type: "num", help: "Empty = the bill's rate" },
    { k: "amount", label: "Amount excl. GST (₹)", type: "num", help: "Empty = qty × rate" },
    { k: "gst", label: "GST %", type: "num", width: 70, help: "Empty = the bill's GST %" },
  ];
  const { rows, setRows, reset } = useRows(cols, { date: today(), what: ctx.lists.reason[0] ?? "" });
  const built = useMemo<Built>(() => {
    const out: Built = { items: [], preview: [], problems: [] };
    const groups = new Map<string, { rows: number[]; bill: Rec; note: { note_no: string | null; date: string;
      lines: Record<string, unknown>[]; expenses: { type: string; amount: number }[] } }>();
    rows.forEach((r, i) => {
      if (!r.bill) return;
      const n = i + 1;
      const bill = bills.get(r.bill);
      if (!bill) { out.problems.push(`Row ${n}: choose the bill from the list.`); return; }
      const g = `${bill.source_row}|${r.note_no.trim() || `auto-${r.date}`}`;
      if (!groups.has(g)) groups.set(g, { rows: [], bill, note: { note_no: r.note_no.trim() || null, date: r.date, lines: [], expenses: [] } });
      const grp = groups.get(g)!;
      grp.rows.push(n);
      const what = r.what.trim() || ctx.lists.reason[0] || "Other";
      if (what.startsWith(EXPENSE)) {
        if (!(num(r.amount) > 0)) out.problems.push(`Row ${n}: type the expense amount.`);
        grp.note.expenses.push({ type: what.slice(EXPENSE.length), amount: num(r.amount) });
      } else {
        const base = num(kind === "Purchase" ? bill.net_amount : bill.amount);
        const billGst = base ? Math.round(num(bill.gst) / base * 200) / 2 : 0;
        const qty = num(r.qty);
        const rate = num(r.rate) || (qty ? num(bill.rate) : 0);
        const taxable = num(r.amount) || round2(qty * rate);
        if (!(taxable > 0)) out.problems.push(`Row ${n}: type the quantity (or the amount).`);
        grp.note.lines.push({ reason: what, qty, rate, taxable, gst_pct: r.gst.trim() === "" ? billGst : num(r.gst) });
      }
    });
    const used = new Set(ctx.note_numbers[kind].map(key));
    for (const g of groups.values()) {
      const qty = g.note.lines.reduce((s, l) => s + num(l.qty), 0);
      if (qty > num(g.bill.qty) + 0.001) out.problems.push(`${rowsText(g.rows)}: quantity ${inr(qty)} kg is more than the `
        + `${inr(num(g.bill.qty))} kg on bill ${g.bill.bill_no ?? "-"} (${g.bill.party}).`);
      if (g.note.note_no && used.has(key(g.note.note_no))) out.problems.push(`${rowsText(g.rows)}: note no. ${g.note.note_no} is already used.`);
      const total = g.note.lines.reduce((s, l) => s + num(l.taxable) * (1 + num(l.gst_pct) / 100), 0)
        + g.note.expenses.reduce((s, e) => s + e.amount, 0);
      out.items.push({ action: "note", label: rowsText(g.rows), body: { kind, row: g.bill.source_row, ...g.note } });
      out.preview.push({ Rows: g.rows.join(", "), Party: String(g.bill.party ?? ""), Bill: String(g.bill.bill_no ?? "-"),
        "Note No": g.note.note_no ?? "(automatic)", Reasons: String(g.note.lines.length), Expenses: String(g.note.expenses.length),
        "Total ₹": total });
    }
    return out;
  }, [rows, ctx]); // eslint-disable-line react-hooks/exhaustive-deps
  return <TableShell cols={cols} rows={rows} setRows={setRows} reset={reset} built={built} busy={busy} save={save}
    what={[name, `${name}s`]} intro={<>One row per reason or expense. Rows on the same bill with the same note no. (or date)
    form one note, so one note can have several reasons and expenses. Expenses carry no GST.</>} />;
}

// ------------------------------------------------------------------------------------------ ④ expenses
export function ExpenseTable({ ctx, save, busy }: FormProps) {
  const [kind, setKind] = useState<Side>("Purchase");
  const [party, setParty] = useState("");
  const fields = Object.values(ctx.expense_fields[kind]).flat();
  const cols: TCol[] = [
    { k: "row", label: "Sheet row", readOnly: true, width: 70 }, { k: "party", label: "Party", readOnly: true, width: 200 },
    { k: "bill_no", label: "Bill No", readOnly: true }, { k: "bill_date", label: "Bill Date", readOnly: true },
    { k: "commodity", label: "Product", readOnly: true },
    ...fields.map((f) => ({ k: f, label: LABELS[f] ?? f, type: "num" as const, width: 95 })),
  ];
  const start = () => [...ctx.bills[kind]].filter((b) => !party || key(b.party) === key(party)).sort(byDateDesc)
    .map((b) => ({ row: String(b.source_row), party: String(b.party ?? ""), bill_no: String(b.bill_no ?? ""),
      bill_date: String(b.bill_date ?? ""), commodity: String(b.commodity ?? ""),
      ...Object.fromEntries(fields.map((f) => [f, b[f] == null ? "" : String(b[f])])) }));
  const [base, setBase] = useState<Row[]>(start);
  const [rows, setRows] = useState<Row[]>(base);
  const edited = rows.some((r, i) => fields.some((f) => r[f] !== base[i]?.[f]));
  useEffect(() => { if (!edited) { const s = start(); setBase(s); setRows(s); } },
    [kind, party, ctx.version]); // eslint-disable-line react-hooks/exhaustive-deps
  const built = useMemo<Built>(() => {
    const out: Built = { items: [], preview: [], problems: [] };
    rows.forEach((r, i) => {
      const was = base[i];
      const changes: Record<string, number> = {};
      for (const f of fields) {
        if (r[f] === was?.[f]) continue;
        if (r[f].trim() !== "" && !isFinite(Number(r[f].replace(/,/g, "")))) out.problems.push(`Row ${i + 1}: ${LABELS[f] ?? f} is not a number.`);
        if (Math.abs(num(r[f]) - num(was?.[f])) > 0.005 || (r[f].trim() === "") !== (was?.[f].trim() === "")) changes[f] = num(r[f]);
      }
      if (!Object.keys(changes).length) return;
      out.items.push({ action: "expenses", label: `Bill ${r.bill_no || "-"} (row ${r.row})`, body: { kind, row: Number(r.row), changes } });
      out.preview.push({ Party: r.party, "Bill No": r.bill_no, Changed: Object.entries(changes)
        .map(([f, v]) => `${LABELS[f] ?? f} ${money2(v)}`).join(", ") });
    });
    return out;
  }, [rows, base]); // eslint-disable-line react-hooks/exhaustive-deps
  const parties = [...new Set(ctx.bills[kind].map((b) => String(b.party ?? "")).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  return (
    <>
      <div className="form-grid">
        <label className="field"><span className="field-label">Bill type</span>
          <select value={kind} disabled={edited} onChange={(e) => { setKind(e.target.value as Side); setParty(""); }}>
            <option value="Purchase">Purchase bills</option><option value="Sales">Sales bills</option></select></label>
        <label className="field"><span className="field-label">Party</span>
          <Combo value={party} onChange={setParty} options={parties} strict placeholder="All parties" /></label>
      </div>
      {kind === "Purchase" && <p className="muted small">Pre-bill expenses and discount are entered with the purchase invoice.</p>}
      <TableShell cols={cols} rows={rows} setRows={setRows} fixed built={built} busy={busy} save={save}
        reset={() => { const s = start(); setBase(s); setRows(s); }} what={["bill with changed expenses", "bills with changed expenses"]}
        intro={<>Change the amounts in the white columns and save: only the cells you change are written.</>} />
    </>
  );
}

// ------------------------------------------------------------------------------------------ ⑤ / ⑨ payments & receipts
export function SettlementTable({ ctx, save, busy, kind }: FormProps & { kind: Side }) {
  const name = kind === "Purchase" ? "payment" : "receipt";
  const due = useMemo(() => new Map([...ctx.outstanding[kind]].sort((a, b) => a.party.localeCompare(b.party))
    .map((b) => [`${b.party} · Bill ${b.bill_no ?? "-"} · due ₹${inr(b.outstanding)} · row ${b.row}`, b])), [ctx, kind]);
  const cols: TCol[] = [
    { k: "date", label: "Date", type: "date" },
    { k: "bill", label: "Invoice", options: [...due.keys()], strict: true, width: 380,
      help: `Only parties with an unpaid bill are listed; a new party first needs a bill` },
    { k: "amount", label: "Amount (₹)", type: "num", help: "Empty = clear the invoice in full" },
    { k: "tds", label: "TDS (₹)", type: "num" },
    { k: "advance", label: "Keep extra as advance", type: "check", width: 90,
      help: "Tick to allow more than the invoice's outstanding; the extra stays as an advance, as in the form" },
  ];
  const { rows, setRows, reset } = useRows(cols, { date: today() });
  const built = useMemo<Built>(() => {
    const out: Built = { items: [], preview: [], problems: [] };
    const groups = new Map<string, { rows: number[]; party: string; date: string;
      alloc: { row: number; amount: number; tds: number; outstanding: number }[] }>();
    rows.forEach((r, i) => {
      if (!r.bill) return;
      const n = i + 1;
      const b = due.get(r.bill);
      if (!b) { out.problems.push(`Row ${n}: choose the invoice from the list.`); return; }
      const tds = num(r.tds);
      const amt = round2(num(r.amount) || Math.max(b.outstanding - tds, 0));
      if (amt + tds > b.outstanding + 1 && r.advance !== "1") out.problems.push(`Row ${n}: ₹ ${fmtRate(amt + tds)} is more `
        + `than the ₹ ${fmtRate(b.outstanding)} outstanding on bill ${b.bill_no ?? "-"} (${b.party}). Type a smaller `
        + "amount, or tick Keep extra as advance.");
      const g = `${key(b.party)}|${r.date}`;
      if (!groups.has(g)) groups.set(g, { rows: [], party: b.party, date: r.date, alloc: [] });
      groups.get(g)!.rows.push(n);
      groups.get(g)!.alloc.push({ row: b.row, amount: amt, tds, outstanding: b.outstanding });
    });
    for (const g of groups.values()) {
      out.items.push({ action: "settlement", label: rowsText(g.rows), body: { kind, date: g.date, allocations: g.alloc } });
      out.preview.push({ Rows: g.rows.join(", "), Party: g.party, Date: g.date, Invoices: String(g.alloc.length),
        "Amount ₹": g.alloc.reduce((s, a) => s + a.amount, 0), "TDS ₹": g.alloc.reduce((s, a) => s + a.tds, 0) });
    }
    return out;
  }, [rows, ctx]); // eslint-disable-line react-hooks/exhaustive-deps
  return <TableShell cols={cols} rows={rows} setRows={setRows} reset={reset} built={built} busy={busy} save={save}
    what={[name, `${name}s`]} intro={<>One row per invoice the {name} is adjusted against. One {name} can be spread over
    several invoices by using several rows with the same date.</>} />;
}

