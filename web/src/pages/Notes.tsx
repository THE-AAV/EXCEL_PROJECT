import DataGrid, { type Col } from "../components/DataGrid";
import { useData } from "../session";

const COLS: Col[] = [
  ["note_no", "Note no."], ["date", "Date", "date"], ["party", "Party"], ["bill_no", "Bill no."], ["product", "Product"],
  ["qty", "Qty (kg)", "qty"], ["rate", "Rate", "rate"], ["taxable", "Taxable value", "money"], ["gst_pct", "GST %", "rate"],
  ["gst", "GST", "money"], ["other", "Other charges", "money"], ["total", "Total", "money"], ["reason", "Reason"],
];

export default function Notes() {
  const { reports } = useData();
  if (!reports) return null;
  return (
    <>
      <h2>Debit notes <span className="muted">(to suppliers)</span></h2>
      <DataGrid rows={reports.debit_notes} cols={COLS} height="auto" exportName="debit_notes" emptyText="No debit notes" />
      <h2>Credit notes <span className="muted">(to customers)</span></h2>
      <DataGrid rows={reports.credit_notes} cols={COLS} height="auto" exportName="credit_notes" emptyText="No credit notes" />
    </>
  );
}
