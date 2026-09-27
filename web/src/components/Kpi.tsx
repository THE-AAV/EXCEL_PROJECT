export default function Kpi({ label, value, note, tone }: {
  label: string;
  value: string;
  note?: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${tone ?? ""}`}>{value}</div>
      {note && <div className="kpi-note">{note}</div>}
    </div>
  );
}
