import { useState } from "react";
import type { Row } from "../api";
import DataGrid from "../components/DataGrid";
import { inr, pct, rate } from "../format";
import { useData } from "../session";

const STATEMENT: [string, string | null][] = [
  ["Purchase", null], ["Purchase qty (kg)", "purchase_qty"], ["Less: qty on debit notes (kg)", "purchase_return_qty"],
  ["Net purchase qty (kg)", "net_purchase_qty"], ["Purchase value", "purchase_value"],
  ["Add: pre-bill expenses", "pre_bill_exp"], ["Less: purchase discount", "purchase_discount"],
  ["Less: debit notes", "purchase_returns"], ["Net purchase cost", "net_purchase"], ["Avg landed cost / kg", "avg_cost_rate"],
  ["Sales", null], ["Sales qty (kg)", "sales_qty"], ["Less: qty on credit notes (kg)", "sales_return_qty"],
  ["Net sales qty (kg)", "net_sales_qty"], ["Sales value", "sales_value"], ["Less: sales discount", "sales_discount"],
  ["Less: credit notes", "sales_returns"], ["Net sales", "net_sales"], ["Avg sale rate / kg", "avg_sales_rate"],
  ["Stock", null], ["Closing stock qty (kg)", "closing_qty"], ["Closing stock value", "closing_value"],
  ["Profit & loss", null], ["Cost of goods sold", "cogs"], ["Gross profit", "gross_profit"],
  ["Less: post-bill exp. (purchase)", "post_exp_purchase"], ["Less: post-bill exp. (sales)", "post_exp_sales"],
  ["Net profit / (loss)", "net_profit"], ["Net margin", "margin_pct"],
];

const n = (r: Row, k: string) => (typeof r[k] === "number" ? (r[k] as number) : 0);

function totalRow(pnl: Row[]): Row {
  const t: Row = {};
  for (const [, key] of STATEMENT) if (key) t[key] = pnl.reduce((s, r) => s + n(r, key), 0);
  t.avg_cost_rate = n(t, "net_purchase_qty") ? n(t, "net_purchase") / n(t, "net_purchase_qty") : 0;
  t.avg_sales_rate = n(t, "net_sales_qty") ? n(t, "net_sales") / n(t, "net_sales_qty") : 0;
  t.margin_pct = n(t, "net_sales") ? n(t, "net_profit") / n(t, "net_sales") : 0;
  return t;
}

export default function Pnl() {
  const { reports } = useData();
  const [pick, setPick] = useState("");
  if (!reports) return null;
  const { pnl, margins } = reports;
  const row = pick ? pnl.find((r) => r.product === pick) ?? totalRow(pnl) : totalRow(pnl);

  return (
    <>
      <h2>Product-wise profit & loss <span className="muted">(exclusive of GST)</span></h2>
      {!pnl.length ? <p className="muted">No purchases or sales match the filters.</p> : (
        <div className="two-col">
          <div className="card">
            <label className="field-label">Statement for</label>
            <select value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">All products (total)</option>
              {pnl.map((r) => <option key={String(r.product)}>{String(r.product)}</option>)}
            </select>
            <table className="statement">
              <tbody>
                {STATEMENT.map(([label, key]) => key == null ? (
                  <tr key={label} className="section"><td colSpan={2}>{label}</td></tr>
                ) : (
                  <tr key={key} className={["net_purchase", "net_sales", "net_profit", "gross_profit"].includes(key) ? "strong" : ""}>
                    <td>{label}</td>
                    <td className="num">{key === "margin_pct" ? pct(row[key]) : key.includes("rate") ? rate(row[key]) : inr(row[key])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {pick && typeof row.remark === "string" && row.remark && <div className="notice">{row.remark}</div>}
          </div>
          <div className="hint card">
            <b>How it is worked out</b>
            <ul>
              <li>All figures are before GST.</li>
              <li>Net purchase cost = purchase value + pre-bill expenses (Adhat, AMC, labour, transport, WH load, bags,
                other) − discount − debit notes.</li>
              <li>Debit / credit note quantities come off the kg bought / sold; their value before GST plus other
                charges comes off purchases / sales.</li>
              <li>Stock not yet sold is valued at the average landed cost per kg and carried forward, so the P&L only
                carries the cost of what was sold.</li>
              <li>Post-bill expenses (storage, brokerage, sampling, repacking, transport, loading) are charged in full.</li>
            </ul>
          </div>
        </div>
      )}
      <h3>All products</h3>
      <DataGrid rows={pnl} exportName="product_pnl" height="auto" cols={[
        ["product", "Product"], ["purchase_qty", "Purchase qty (kg)", "qty"], ["net_purchase", "Net purchase", "money"],
        ["avg_cost_rate", "Cost / kg", "rate"], ["sales_qty", "Sales qty (kg)", "qty"], ["net_sales", "Net sales", "money"],
        ["avg_sales_rate", "Sale / kg", "rate"], ["closing_qty", "Closing qty (kg)", "qty"],
        ["closing_value", "Closing stock", "money"], ["gross_profit", "Gross profit", "money"],
        ["post_bill_exp", "Post-bill exp.", "money"], ["net_profit", "Net profit", "money"], ["margin_pct", "Margin", "pct"],
        ["remark", "Remark"]]} />
      <h3>Bill-wise margin <span className="muted">(sales bills linked to a purchase bill)</span></h3>
      <DataGrid rows={margins} exportName="bill_margin" height="auto" emptyText="No sales bills are linked to a purchase bill yet"
        cols={[["sales_bill", "Sales bill"], ["sales_date", "Date", "date"], ["customer", "Customer"], ["product", "Product"],
          ["qty", "Qty (kg)", "qty"], ["sale_rate", "Sale / kg", "rate"], ["purchase_bill", "Purchase bill"],
          ["supplier", "Supplier"], ["cost_rate", "Cost / kg", "rate"], ["margin", "Margin", "money"],
          ["margin_per_kg", "Margin / kg", "rate"], ["margin_pct", "Margin %", "pct"]]} />
    </>
  );
}
