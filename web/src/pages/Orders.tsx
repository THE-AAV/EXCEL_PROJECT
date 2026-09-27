import { useState } from "react";
import DataGrid, { type Col } from "../components/DataGrid";
import { useData } from "../session";

const COLS: Col[] = [
  ["contract_no", "Contract no."], ["date", "Date", "date"], ["party", "Party"], ["broker", "Broker"], ["product", "Product"],
  ["qty_mt", "Qty (MT)", "rate"], ["cancel_qty", "Cancelled (MT)", "rate"], ["recd_qty", "Done (MT)", "rate"],
  ["bal_qty_mt", "Balance (MT)", "rate"], ["rate", "Rate / kg", "rate"], ["order_value", "Order value", "money"],
  ["done_pct", "% done", "pct"], ["status", "Status"], ["delivery_date", "Delivery date", "date"],
  ["delivery_place", "Delivery place"], ["bill_no", "Bills"], ["days_open", "Days open", "int"],
];

export default function Orders() {
  const { reports } = useData();
  const [tab, setTab] = useState<"po" | "so">("po");
  if (!reports) return null;
  return (
    <>
      <h2>Purchase & sales orders</h2>
      <h3>Open orders by product</h3>
      <DataGrid rows={reports.open_orders} height="auto" search={false} emptyText="No open orders" cols={[
        ["order_type", "Order type"], ["product", "Product"], ["contracts", "Contracts", "int"],
        ["bal_qty_kg", "Balance (kg)", "qty"], ["amount", "Value", "money"], ["avg_rate", "Avg rate / kg", "rate"]]} />
      <div className="tabs">
        <button className={tab === "po" ? "active" : ""} onClick={() => setTab("po")}>Purchase orders ({reports.po.length})</button>
        <button className={tab === "so" ? "active" : ""} onClick={() => setTab("so")}>Sales orders ({reports.so.length})</button>
      </div>
      <DataGrid key={tab} rows={reports[tab]} cols={COLS} exportName={tab === "po" ? "purchase_orders" : "sales_orders"} />
    </>
  );
}
