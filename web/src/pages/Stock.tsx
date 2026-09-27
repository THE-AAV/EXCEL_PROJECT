import DataGrid from "../components/DataGrid";
import { useData } from "../session";

export default function Stock() {
  const { reports } = useData();
  if (!reports) return null;
  return (
    <>
      <h2>Stock summary <span className="muted">(kg)</span></h2>
      <DataGrid rows={reports.stock} exportName="stock_summary" height="auto" cols={[
        ["product", "Product"], ["purchase_qty", "Purchased", "qty"], ["purchase_return_qty", "Returned to suppliers", "qty"],
        ["sales_qty", "Sold", "qty"], ["sales_return_qty", "Returned by customers", "qty"], ["closing_qty", "In stock", "qty"],
        ["avg_cost_rate", "Avg cost / kg", "rate"], ["closing_value", "Stock value", "money"],
        ["pending_po_qty", "Still to come in (open POs)", "qty"], ["pending_so_qty", "Still to go out (open SOs)", "qty"],
        ["projected_qty", "Projected stock", "qty"]]} />
    </>
  );
}
