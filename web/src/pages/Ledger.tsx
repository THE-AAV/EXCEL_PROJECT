import { useState } from "react";
import type { Row } from "../api";
import DataGrid, { type Col } from "../components/DataGrid";
import { inr } from "../format";
import { useData } from "../session";

export default function Ledger({ side }: { side: "creditors" | "debtors" }) {
  const { reports } = useData();
  const [party, setParty] = useState<string | null>(null);
  if (!reports) return null;
  const { summary, bills } = reports[side];
  const cred = side === "creditors";
  const cols: Col[] = [
    ["party", "Party"], ["opening", "Opening", "money"], ["billed", cred ? "Payable (bills)" : "Receivable (bills)", "money"],
    ["paid", cred ? "Paid" : "Received", "money"], ["tds", "TDS", "money"],
    ["note", cred ? "Debit notes" : "Credit notes", "money"], ["closing", "Closing balance", "money"],
    ...reports.age_buckets.map((b) => [b, b, "money"] as Col),
    ["advance", "Advance", "money"], ["oldest_days", "Oldest (days)", "int"], ["last_payment", cred ? "Last paid" : "Last received", "date"],
  ];
  const partyBills = party ? bills.filter((b) => b.party === party) : [];
  const total = (rows: Row[], k: string) => rows.reduce((s, r) => s + (typeof r[k] === "number" ? (r[k] as number) : 0), 0);

  return (
    <>
      <h2>{cred ? "Creditors (we pay)" : "Debtors (we receive)"} <span className="muted">amounts include GST</span></h2>
      <p className="hint">Click a party to see its outstanding bills. Payments clear the opening balance first, then the
        oldest bills.</p>
      <DataGrid rows={summary} cols={cols} exportName={side} height={Math.min(560, 90 + summary.length * 34)}
        onRowClick={(r) => setParty(String(r.party))} />
      {party && (
        <div className="card">
          <div className="card-head">
            <h3>Outstanding bills: {party}</h3>
            <span className="muted">₹{inr(total(partyBills, "outstanding"))} outstanding</span>
            <button className="link" onClick={() => setParty(null)}>Close</button>
          </div>
          <DataGrid rows={partyBills} height="auto" search={false} emptyText="Nothing outstanding" cols={[
            ["bill_no", "Bill no."], ["bill_date", "Bill date", "date"], ["product", "Product"],
            ["bill_amount", "Bill amount", "money"], ["outstanding", "Outstanding", "money"], ["days", "Days", "int"],
            ["age_bucket", "Age"]]} />
        </div>
      )}
      <h3>All outstanding bills</h3>
      <DataGrid rows={bills} exportName={`${side}_bills`} cols={[
        ["party", "Party"], ["bill_no", "Bill no."], ["bill_date", "Bill date", "date"], ["product", "Product"],
        ["bill_amount", "Bill amount", "money"], ["outstanding", "Outstanding", "money"], ["days", "Days", "int"],
        ["age_bucket", "Age"]]} />
    </>
  );
}
