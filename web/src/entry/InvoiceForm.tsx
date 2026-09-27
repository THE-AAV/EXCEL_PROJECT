import { useEffect, useMemo, useState } from "react";
import { day, inr, rate as fmtRate, today } from "../format";
import { Combo, Field, key, LABELS, money2, Num, num, partyDefaults, Preview, round2, type FormProps, type Rec,
  type Side } from "./common";

interface Item { id: number; order: string; commodity: string; qty: string; rate: string; link: string }

const newItem = (id: number): Item => ({ id, order: "", commodity: "", qty: "", rate: "", link: "" });

/** Splits a total over items in proportion to their value (the last item takes the rounding difference). */
function split(total: number, weights: number[]): number[] {
  const sum = weights.reduce((a, b) => a + b, 0);
  if (!sum) return weights.map((_, i) => (i === 0 ? total : 0));
  const parts = weights.map((w) => round2((total * w) / sum));
  parts[parts.length - 1] = round2(total - parts.slice(0, -1).reduce((a, b) => a + b, 0));
  return parts;
}

const orderLabel = (o: Rec) =>
  `Contract ${o.contract_no} · ${o.party} · ${o.commodity} · balance ${o.bal_qty_mt} MT @ ₹${o.rate}/kg`;
const billLabel = (b: Rec) =>
  `Bill ${b.bill_no ?? "-"} · ${b.party} · ${b.bill_date ? day(b.bill_date) : "no date"} · ${b.commodity} ${inr(b.qty)} kg @ ₹${b.rate}`;

export default function InvoiceForm({ ctx, save, busy, kind }: FormProps & { kind: Side }) {
  const purchase = kind === "Purchase";
  const okind = purchase ? "PO" : "SO";
  const L = ctx.lists;
  const blankHead = { party: "", bill_no: purchase ? "" : String(ctx.next.sales_bill), bill_date: today(),
    stock_date: "", truck_no: "", company: "", type: "", sub_type: "", broker: "", warehouse: "", gstin: "",
    branch: "" };
  const [h, setH] = useState(blankHead);
  const [gst, setGst] = useState("5");
  const [items, setItems] = useState<Item[]>([newItem(1)]);
  const [exp, setExp] = useState<Record<string, string>>({});
  const [tab, setTab] = useState<"items" | "exp" | "more">("items");
  const [dupOk, setDupOk] = useState(false);
  const setHead = (k: keyof typeof blankHead) => (v: string) => setH((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    if (!purchase) setH((x) => ({ ...x, bill_no: x.bill_no || String(ctx.next.sales_bill) }));
  }, [ctx.next.sales_bill]); // eslint-disable-line react-hooks/exhaustive-deps

  // a known party: fill in its usual details, and GST 0% for imports
  useEffect(() => {
    const d = partyDefaults(ctx, kind, h.party);
    setH((x) => ({ ...x, company: d.company ?? x.company ?? "", type: d.type ?? (x.type || "Local"),
      sub_type: d.sub_type ?? x.sub_type, broker: d.broker ?? x.broker, warehouse: d.warehouse ?? x.warehouse,
      gstin: d.gstin ?? x.gstin, branch: d.branch ?? x.branch }));
    if (d.type) setGst(d.type === "Import" ? "0" : "5");
  }, [h.party]); // eslint-disable-line react-hooks/exhaustive-deps

  const orders = useMemo(() => {
    const all = ctx.orders[okind];
    const mine = all.filter((o) => key(o.party) === key(h.party));
    return mine.length ? mine : all;
  }, [ctx, okind, h.party]);
  const orderByRow = (row: string) => ctx.orders[okind].find((o) => String(o.source_row) === row);

  const setItem = (id: number, patch: Partial<Item>) =>
    setItems((xs) => xs.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  const pickOrder = (id: number, row: string) => {
    const o = orderByRow(row);
    if (!o) return setItem(id, { order: "" });
    const product = L.product.find((p) => key(p) === key(o.commodity)) ?? String(o.commodity ?? "");
    setItem(id, { order: row, commodity: product, qty: String(round2(num(o.bal_qty_mt) * 1000)), rate: String(o.rate ?? "") });
  };

  // ---- preview (the same sums the sheet's formulas make)
  const values = items.map((i) => num(i.qty) * num(i.rate));
  const shares = Object.fromEntries(Object.entries(exp).filter(([, v]) => num(v)).map(([k, v]) => [k, split(num(v), values)]));
  const lines = items.map((_, n) => {
    const amount = values[n];
    const extra = Object.entries(shares).reduce((s, [k, v]) => s + (k === "discount" ? -v[n] : v[n]), 0);
    const base = purchase ? amount + extra : amount;
    const g = round2((base * num(gst)) / 100);
    return { amount, extra, gst: g, bill: amount + g };
  });
  const total = (k: "amount" | "gst" | "bill") => lines.reduce((s, l) => s + l[k], 0);

  const bills = ctx.bills[kind];
  const dup = h.bill_no.trim() !== "" &&
    bills.some((b) => key(b.party) === key(h.party) && key(b.bill_no) === key(h.bill_no));
  const itemsOk = items.every((i) => i.commodity.trim() && num(i.qty) > 0 && num(i.rate) > 0);
  const ready = h.party.trim() && h.bill_date && itemsOk && (!dup || dupOk);

  const purchaseBills = (product: string) => {
    const pb = ctx.bills.Purchase.filter((b) => num(b.qty) > 0);
    const same = product ? pb.filter((b) => key(b.commodity) === key(product)) : pb;
    return (same.length ? same : pb).slice().sort((a, b) => String(b.bill_date ?? "").localeCompare(String(a.bill_date ?? "")))
      .slice(0, 300);
  };

  const submit = async () => {
    const ok = await save("invoice", {
      kind,
      header: { ...h, stock_date: h.stock_date || h.bill_date },
      lines: items.map((i) => ({ commodity: i.commodity, qty: num(i.qty), rate: num(i.rate), gst_pct: num(gst),
        order_row: i.order ? Number(i.order) : null, link_row: i.link ? Number(i.link) : null,
        hsn: ctx.hsn[key(i.commodity)] ?? null })),
      expenses: purchase ? Object.fromEntries(Object.entries(exp).filter(([, v]) => num(v)).map(([k, v]) => [k, num(v)])) : {},
    });
    if (ok) {
      setH({ ...blankHead, bill_no: "" });
      setItems([newItem(1)]);
      setExp({});
      setDupOk(false);
    }
  };

  return (
    <>
      <p className="hint">One bill can have several items, each against a different {purchase ? "purchase" : "sales"} contract.
        {!purchase && " An item can also be linked to the purchase bill the goods came from."}</p>
      <div className="form-grid">
        <Field label={purchase ? "Supplier" : "Customer"} required>
          <Combo value={h.party} onChange={setHead("party")} options={L[`party:${kind}`]} />
        </Field>
        <Field label={purchase ? "Supplier's bill No." : "Our invoice No."}
          hint={purchase ? undefined : "Next number in the series; change it if needed"}>
          <input value={h.bill_no} onChange={(e) => setHead("bill_no")(e.target.value)} />
        </Field>
        <Field label="Bill date" required><input type="date" value={h.bill_date} onChange={(e) => setHead("bill_date")(e.target.value)} /></Field>
        <Field label={purchase ? "WH in date" : "Delivery date"} hint="Same as the bill date if left empty">
          <input type="date" value={h.stock_date} onChange={(e) => setHead("stock_date")(e.target.value)} />
        </Field>
        <Field label="Truck No."><input value={h.truck_no} onChange={(e) => setHead("truck_no")(e.target.value)} /></Field>
        <Field label="GST % (all items)"><Num value={gst} onChange={setGst} step={0.5} /></Field>
      </div>

      <div className="tabs">
        <button className={tab === "items" ? "active" : ""} onClick={() => setTab("items")}>Items ({items.length})</button>
        {purchase && <button className={tab === "exp" ? "active" : ""} onClick={() => setTab("exp")}>Pre-bill expenses</button>}
        <button className={tab === "more" ? "active" : ""} onClick={() => setTab("more")}>More details</button>
      </div>

      {tab === "items" && (
        <>
          {items.map((it, n) => (
            <div className="item-card" key={it.id}>
              <div className="item-head">
                <b>Item {n + 1}</b>
                {items.length > 1 && <button className="link" onClick={() => setItems((xs) => xs.filter((x) => x.id !== it.id))}>Remove</button>}
              </div>
              <div className="form-grid">
                <Field label="Against contract" wide>
                  <select value={it.order} onChange={(e) => pickOrder(it.id, e.target.value)}>
                    <option value="">No contract</option>
                    {orders.map((o) => <option key={String(o.source_row)} value={String(o.source_row)}>{orderLabel(o)}</option>)}
                  </select>
                </Field>
                <Field label="Product" required><Combo value={it.commodity} onChange={(v) => setItem(it.id, { commodity: v })} options={L.product} /></Field>
                <Field label="Weight (kg)" required><Num value={it.qty} onChange={(v) => setItem(it.id, { qty: v })} step={10} /></Field>
                <Field label="Rate (₹ per kg)" required><Num value={it.rate} onChange={(v) => setItem(it.id, { rate: v })} /></Field>
                {!purchase && (
                  <Field label="Linked purchase bill (optional)" wide
                    hint="The purchase bill these goods came from, for the bill-wise margin report">
                    <select value={it.link} onChange={(e) => setItem(it.id, { link: e.target.value })}>
                      <option value="">Not linked</option>
                      {purchaseBills(it.commodity).map((b) => <option key={String(b.source_row)} value={String(b.source_row)}>{billLabel(b)}</option>)}
                    </select>
                  </Field>
                )}
              </div>
            </div>
          ))}
          <button className="secondary" onClick={() => setItems((xs) => [...xs, newItem(Math.max(...xs.map((x) => x.id)) + 1)])}>
            + Add another item
          </button>
        </>
      )}

      {tab === "exp" && purchase && (
        <>
          <p className="hint">Totals for this bill. They are split over the items by value and added to the item cost
            (the discount is taken off).</p>
          <div className="form-grid">
            {ctx.pre_bill_fields.map((k) => (
              <Field key={k} label={k === "discount" ? "Discount (less)" : LABELS[k] ?? k}>
                <Num value={exp[k] ?? ""} onChange={(v) => setExp((x) => ({ ...x, [k]: v }))} step={100} />
              </Field>
            ))}
          </div>
        </>
      )}

      {tab === "more" && (
        <div className="form-grid">
          <Field label="Company"><Combo value={h.company} onChange={setHead("company")} options={L.company} /></Field>
          <Field label="Type"><Combo value={h.type} onChange={(v) => { setHead("type")(v); if (key(v) === "import") setGst("0"); }} options={L.type} /></Field>
          <Field label="Sub type"><Combo value={h.sub_type} onChange={setHead("sub_type")} options={L.sub_type} /></Field>
          <Field label="Broker"><Combo value={h.broker} onChange={setHead("broker")} options={L.broker} /></Field>
          <Field label="Warehouse"><Combo value={h.warehouse} onChange={setHead("warehouse")} options={L.warehouse} /></Field>
          <Field label="Party GSTIN"><input value={h.gstin} onChange={(e) => setHead("gstin")(e.target.value)} /></Field>
          <Field label="Branch"><Combo value={h.branch} onChange={setHead("branch")} options={L.branch} /></Field>
        </div>
      )}

      <h3>Bill preview</h3>
      <table className="plain wide">
        <thead><tr><th>Item</th><th>Product</th><th className="num">Weight (kg)</th><th className="num">Rate</th>
          <th className="num">Amount</th>{purchase && <th className="num">Pre-bill exp. (net)</th>}<th className="num">GST</th>
          <th className="num">Bill amount</th></tr></thead>
        <tbody>
          {items.map((it, n) => (
            <tr key={it.id}><td>{n + 1}</td><td>{it.commodity}</td><td className="num">{inr(num(it.qty))}</td>
              <td className="num">{fmtRate(num(it.rate))}</td><td className="num">{fmtRate(lines[n].amount)}</td>
              {purchase && <td className="num">{fmtRate(lines[n].extra)}</td>}<td className="num">{fmtRate(lines[n].gst)}</td>
              <td className="num">{fmtRate(lines[n].bill)}</td></tr>
          ))}
        </tbody>
      </table>
      <Preview>Total amount <b>{money2(total("amount"))}</b> + GST <b>{money2(total("gst"))}</b> = Bill total <b>{money2(total("bill"))}</b></Preview>
      {dup && (
        <label className="notice warn check">
          <input type="checkbox" checked={dupOk} onChange={(e) => setDupOk(e.target.checked)} />
          Bill {h.bill_no} already exists for {h.party}. Tick to save it again anyway.
        </label>
      )}
      <div className="actions">
        <button className="primary" disabled={!ready || busy} onClick={submit}>Save {kind.toLowerCase()} invoice</button>
        {!itemsOk && <span className="muted">Each item needs a product, weight and rate.</span>}
      </div>
    </>
  );
}
