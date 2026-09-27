import { useEffect, useState } from "react";
import DataGrid from "../components/DataGrid";
import { today } from "../format";
import { Combo, Field, Num, Numbering, numberingOk, num, partyDefaults, Preview, money2, type FormProps } from "./common";

export default function OrderForm({ ctx, save, busy, kind }: FormProps & { kind: "PO" | "SO" }) {
  const side = kind === "PO" ? "Purchase" : "Sales";
  const blank = { party: "", commodity: "", broker: "", date: today(), qty_mt: "", rate: "", delivery_date: "",
    delivery_place: "", packing: "", company: "", warehouse: "", branch: "" };
  const [f, setF] = useState(blank);
  const [auto, setAuto] = useState(true);
  const [own, setOwn] = useState("");
  const set = (k: keyof typeof blank) => (v: string) => setF((x) => ({ ...x, [k]: v }));

  // a known party: fill in its usual broker, company, warehouse and branch
  useEffect(() => {
    const d = partyDefaults(ctx, side, f.party);
    setF((x) => ({ ...x, broker: d.broker ?? x.broker, company: d.company ?? x.company,
      warehouse: d.warehouse ?? x.warehouse, branch: d.branch ?? x.branch }));
  }, [f.party]); // eslint-disable-line react-hooks/exhaustive-deps

  const value = num(f.qty_mt) * 1000 * num(f.rate);
  const ready = f.party.trim() && f.commodity.trim() && num(f.qty_mt) > 0 && num(f.rate) > 0 && f.date &&
    numberingOk(auto, own, ctx.all_contracts[kind]);
  const L = ctx.lists;

  return (
    <>
      <div className="form-grid">
        <Numbering label="Contract No." next={ctx.next[kind]} used={ctx.all_contracts[kind]} own={own} setOwn={setOwn}
          auto={auto} setAuto={setAuto} />
        <Field label={kind === "PO" ? "Supplier" : "Customer"} required>
          <Combo value={f.party} onChange={set("party")} options={L[`party:${side}`]} />
        </Field>
        <Field label="Product" required><Combo value={f.commodity} onChange={set("commodity")} options={L.product} /></Field>
        <Field label="Broker"><Combo value={f.broker} onChange={set("broker")} options={L.broker} /></Field>
        <Field label="Order date" required><input type="date" value={f.date} onChange={(e) => set("date")(e.target.value)} /></Field>
        <Field label="Quantity (MT)" required><Num value={f.qty_mt} onChange={set("qty_mt")} /></Field>
        <Field label="Rate (₹ per kg)" required><Num value={f.rate} onChange={set("rate")} /></Field>
        <Field label="Delivery date"><input type="date" value={f.delivery_date} onChange={(e) => set("delivery_date")(e.target.value)} /></Field>
        <Field label="Delivery place"><Combo value={f.delivery_place} onChange={set("delivery_place")} options={L.place} /></Field>
        <Field label="Packing"><Combo value={f.packing} onChange={set("packing")} options={L.packing} /></Field>
        <Field label="Company"><Combo value={f.company} onChange={set("company")} options={L.company} /></Field>
        <Field label="Warehouse"><Combo value={f.warehouse} onChange={set("warehouse")} options={L.warehouse} /></Field>
        <Field label="Branch"><Combo value={f.branch} onChange={set("branch")} options={L.branch} /></Field>
      </div>
      <Preview>Order value: <b>{money2(value)}</b> ({num(f.qty_mt) || 0} MT × 1000 × ₹{num(f.rate) || 0}/kg)</Preview>
      <div className="actions">
        <button className="primary" disabled={!ready || busy} onClick={async () => {
          const ok = await save("order", { kind, contract_no: auto ? null : own.trim(), fields: f });
          if (ok) { setF(blank); setOwn(""); }
        }}>Save {side.toLowerCase()} order</button>
      </div>

      <h3>Open {side.toLowerCase()} orders</h3>
      <DataGrid rows={ctx.orders[kind]} height="auto" search={false} emptyText="No open orders" cols={[
        ["contract_no", "Contract"], ["date", "Date", "date"], ["party", "Party"], ["commodity", "Product"],
        ["qty_mt", "Qty (MT)", "rate"], ["bal_qty_mt", "Balance (MT)", "rate"], ["rate", "Rate / kg", "rate"],
        ["amount", "Balance ₹", "money"]]} />
    </>
  );
}
