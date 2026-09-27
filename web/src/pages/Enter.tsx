import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { ExpenseForm, NoteForm, SettlementForm } from "../entry/BillForms";
import type { EntryContext } from "../entry/common";
import InvoiceForm from "../entry/InvoiceForm";
import OrderForm from "../entry/OrderForm";
import { rate as fmtRate, when } from "../format";
import { useData } from "../session";

const STEPS = ["Purchase Order", "Purchase Invoice", "Debit Note", "Expenses", "Payment",
  "Sales Order", "Sales Invoice", "Credit Note", "Receipt"] as const;
type Step = (typeof STEPS)[number];

interface Recent {
  id: number; entry: string; status: string; by: string | null; at: string;
  lines: { Action: string; Party: string; Amount: string; Details: string }[];
}

export default function Enter() {
  const { reload, version } = useData();
  const [step, setStep] = useState<Step>(() => (sessionStorage.getItem("entry-step") as Step) || "Purchase Order");
  const [ctx, setCtx] = useState<EntryContext | null>(null);
  const [recent, setRecent] = useState<Recent[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ good: boolean; text: string } | null>(null);
  const [confirmUndo, setConfirmUndo] = useState(false);

  const load = useCallback(async () => {
    const [c, r] = await Promise.all([api<EntryContext>("/entry/context"), api<Recent[]>("/entry-recent")]);
    setCtx(c);
    setRecent(r);
  }, []);
  useEffect(() => { load().catch((e) => setMsg({ good: false, text: e.message })); }, [load]);
  // someone else saved something: refresh the lists (a form's typing is kept)
  useEffect(() => {
    if (ctx && version && version !== ctx.version) load().catch(() => undefined);
  }, [version]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (action: string, body: object) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{ message: string }>(`/entry/${action}`, { method: "POST", json: { ...body, version: ctx?.version } });
      setMsg({ good: true, text: `${r.message}. The reports are updated.` });
      await load();
      reload();
      return true;
    } catch (e) {
      setMsg({ good: false, text: (e as Error).message });
      if (e instanceof ApiError && e.status === 409) await load();
      return false;
    } finally {
      setBusy(false);
    }
  };

  const undo = async () => {
    setConfirmUndo(false);
    setBusy(true);
    try {
      const r = await api<{ message: string }>("/entry-undo", { method: "POST" });
      setMsg({ good: true, text: r.message });
      await load();
      reload();
    } catch (e) {
      setMsg({ good: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const pick = (s: Step) => { setStep(s); sessionStorage.setItem("entry-step", s); setMsg(null); };
  const props = ctx ? { ctx, save, busy } : null;
  const canUndo = recent[0]?.status === "active";

  return (
    <>
      <p className="hint">Follow the business flow: order → invoice → note → expenses → payment. Every entry is saved
        straight into the data, the reports update at once, and everyone else sees it within a few seconds.</p>
      <div className="steps">
        <span className="steps-label">Purchase</span>
        {STEPS.slice(0, 5).map((s, i) => <button key={s} className={step === s ? "active" : ""} onClick={() => pick(s)}>
          <span className="step-no">{i + 1}</span>{s.replace("Purchase ", "")}</button>)}
      </div>
      <div className="steps">
        <span className="steps-label">Sales</span>
        {STEPS.slice(5).map((s, i) => <button key={s} className={step === s ? "active" : ""} onClick={() => pick(s)}>
          <span className="step-no">{i + 6}</span>{s.replace("Sales ", "")}</button>)}
      </div>
      {msg && <div className={msg.good ? "notice good" : "error"}>{msg.text}</div>}
      <div className="card">
        <h2 className="card-title">{step}</h2>
        {!props ? <span className="spinner" /> : (
          <div key={step}>
            {step === "Purchase Order" && <OrderForm {...props} kind="PO" />}
            {step === "Purchase Invoice" && <InvoiceForm {...props} kind="Purchase" />}
            {step === "Debit Note" && <NoteForm {...props} kind="Purchase" />}
            {step === "Expenses" && <ExpenseForm {...props} />}
            {step === "Payment" && <SettlementForm {...props} kind="Purchase" />}
            {step === "Sales Order" && <OrderForm {...props} kind="SO" />}
            {step === "Sales Invoice" && <InvoiceForm {...props} kind="Sales" />}
            {step === "Credit Note" && <NoteForm {...props} kind="Sales" />}
            {step === "Receipt" && <SettlementForm {...props} kind="Sales" />}
          </div>
        )}
        {busy && <div className="muted"><span className="spinner" /> Saving…</div>}
      </div>

      <div className="card">
        <div className="card-head">
          <h3>Recent entries</h3>
          {canUndo && !confirmUndo && <button className="link" disabled={busy} onClick={() => setConfirmUndo(true)}>Undo last entry</button>}
          {confirmUndo && (
            <span className="confirm">Undo “{recent[0].entry}”?
              <button className="primary" onClick={undo}>Yes, undo</button>
              <button className="secondary" onClick={() => setConfirmUndo(false)}>Cancel</button></span>
          )}
        </div>
        {recent.length === 0 ? <p className="muted">Nothing entered here yet.</p> : (
          <table className="plain wide">
            <thead><tr><th>When</th><th>By</th><th>Entry</th><th>Details</th><th className="num">Amount</th></tr></thead>
            <tbody>
              {recent.slice(0, 15).map((r) => (
                <tr key={r.id} className={r.status === "undone" ? "inactive" : ""}>
                  <td>{when(r.at)}</td><td>{r.by}</td>
                  <td>{r.entry}{r.status === "undone" && <span className="badge"> undone</span>}</td>
                  <td className="small">{r.lines.map((l) => l.Details).join("; ")}</td>
                  <td className="num">{fmtRate(r.lines.reduce((s, l) => s + (parseFloat(l.Amount) || 0), 0))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
