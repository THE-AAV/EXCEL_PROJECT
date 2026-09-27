import DataGrid from "../components/DataGrid";
import { useData } from "../session";

export default function Checks() {
  const { reports } = useData();
  if (!reports) return null;
  return (
    <>
      <h2>Data checks</h2>
      <p className="hint">Rows with a missing date, quantity or amount, and products sold but never bought. They can make
        the reports less accurate. "Row" is the row number in the imported Master Sheet.</p>
      <DataGrid rows={reports.checks} height="auto" totals={false} emptyText="Everything looks fine"
        cols={[["sheet", "Sheet"], ["row", "Row"], ["party", "Party"], ["issue", "What to check"]]} />
    </>
  );
}
