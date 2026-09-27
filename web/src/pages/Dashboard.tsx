import { Link } from "react-router-dom";
import DataGrid from "../components/DataGrid";
import Kpi from "../components/Kpi";
import { pct, short } from "../format";
import { can, useAuth, useData } from "../session";

export default function Dashboard() {
  const { reports, status } = useData();
  const { user } = useAuth();
  if (status && !status.has_data) {
    return (
      <div className="empty-state">
        <h2>No data yet</h2>
        {can(user, "admin") ? (
          <p>Start by importing your Master Sheet on the <Link to="/import">Import</Link> page. All the reports are
            worked out from it.</p>
        ) : (
          <p>An admin needs to import the Master Sheet before reports appear.</p>
        )}
      </div>
    );
  }
  if (!reports) return null;
  const d = reports.dashboard;
  return (
    <>
      <div className="kpis">
        <Kpi label="Net sales (excl. GST)" value={short(d.net_sales)} />
        <Kpi label="Net profit / loss" value={short(d.net_profit)} tone={d.net_profit < 0 ? "bad" : "good"}
          note={d.net_margin != null ? `${pct(d.net_margin)} margin` : undefined} />
        <Kpi label="Payable to creditors" value={short(d.payable)} note="What we owe suppliers, incl. GST" />
        <Kpi label="Receivable from debtors" value={short(d.receivable)} note="What customers owe us, incl. GST" />
        <Kpi label="Gross profit" value={short(d.gross_profit)} />
        <Kpi label="Closing stock value" value={short(d.closing_stock_value)} />
        <Kpi label="Payable overdue > 90 days" value={short(d.payable_over_90)} tone={d.payable_over_90 > 0 ? "bad" : undefined} />
        <Kpi label="Receivable overdue > 90 days" value={short(d.receivable_over_90)} tone={d.receivable_over_90 > 0 ? "bad" : undefined} />
      </div>
      {d.data_checks > 0 && (
        <div className="notice warn">
          {d.data_checks} row(s) may need attention. See <Link to="/checks">Data checks</Link>.
        </div>
      )}
      {d.products_without_purchase.length > 0 && (
        <div className="notice">
          No purchase found for <b>{d.products_without_purchase.join(", ")}</b>, so its sales are counted without any
          cost. If it was bought under another name, map the names in <Link to="/product-names">Product names</Link>.
        </div>
      )}
      <h2>Stock in hand</h2>
      <DataGrid rows={reports.stock} height="auto" search={false}
        cols={[["product", "Product"], ["closing_qty", "Stock (kg)", "qty"], ["avg_cost_rate", "Avg cost / kg", "rate"],
          ["closing_value", "Stock value", "money"]]} />
    </>
  );
}
