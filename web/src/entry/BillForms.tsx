import { useEffect, useMemo, useState } from "react";
import DataGrid from "../components/DataGrid";
import { day, inr, rate as fmtRate, today } from "../format";
import { Combo, Field, key, LABELS, money2, Num, num, Numbering, numberingOk, Preview, round2, type EntryContext,
  type FormProps, type Rec, type Side } from "./common";

const billLabel = (b: Rec) =>
  `Bill ${b.bill_no ?? "-"} · ${b.bill_date ? day(b.bill_date) : "no date"} · ${b.commodity} · ₹${inr(b.bill_amt ?? b.amount)}`;

/** Party, then one of its bills (the latest is picked). */
function useBill(ctx: EntryContext, kind: Side) {
  const [party, setParty] = useState("");
  const [row, setRow] = useState("");
  const parties = useMemo(() => {
    const seen = new Map<string, string>();
    ctx.bills[kind].forEach((b) => b.party && seen.set(key(b.party), String(b.party)));
    return [...seen.values()].sort((a, b) => a.localeCompare(b));
  }, [ctx, kind]);
  const bills = useMemo(() => ctx.bills[kind].filter((b) => key(b.party) === key(party))
    .sort((a, b) => String(a.bill_date ?? "").localeCompare(String(b.bill_date ?? ""))), [ctx, kind, party]);
  useEffect(() => {
    setRow(bills.length ? String(bills[bills.length - 1].source_row) : "");
  }, [party, bills.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const bill = bills.find((b) => String(b.source_row) === row) ?? null;
  const picker = (
    <>
      <Field label="Party" required>
        <select value={party} onChange={(e) => setParty(e.target.value)}>
          <option value="">Choose party</option>
          {parties.map((p) => <option key={p}>{p}</option>)}
        </select>
      </Field>
      <Field label="Bill" required wide>
        <select value={row} onChange={(e) => setRow(e.target.value)} disabled={!bills.length}>
          {bills.map((b) => <option key={String(b.source_row)} value={String(b.source_row)}>{billLabel(b)}</option>)}
        </select>
      </Field>
    </>
  );
  return { party, bill, picker, reset: () => setParty("") };
}

// --------------------------------------------------------------------------- ③ / ⑧ debit and credit notes
interface Reason { id: number; reason: string; qty: string; rate: string; amount: string; gst: string }
interface Expense { id: number; type: string; amount: string }

export function NoteForm({ ctx, save, busy, kind }: FormProps & { kind: Side }) {
  const name = kind === "Purchase" ? "Debit note" : "Credit note";
  const { party, bill, picker, reset } = useBill(ctx, kind);
  const [auto, setAuto] = useState(true);
  const [own, setOwn] = useState("");
  const [date, setDate] = useState(today());
  const billRate = bill ? String(bill.rate ?? "") : "";
  const base = bill ? num(kind === "Purchase" ? bill.net_amount : bill.amount) : 0;
  const billGst = bill && base ? String(Math.round((num(bill.gst) / base) * 200) / 2) : "0";
  const [reasons, setReasons] = useState<Reason[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  useEffect(() => {
    setReasons([{ id: 1, reason: ctx.lists.reason[0], qty: "", rate: billRate, amount: "", gst: billGst }]);
    setExpenses([]);
  }, [bill?.source_row]); // eslint-disable-line react-hooks/exhaustive-deps

  const lines = reasons.map((r) => {
    const value = num(r.amount) || round2(num(r.qty) * num(r.rate));
    const gst = round2((value * num(r.gst)) / 100);
    return { ...r, value, gstAmt: gst, total: value + gst };
  });
  const total = lines.reduce((s, l) => s + l.total, 0) + expenses.reduce((s, e) => s + num(e.amount), 0);
  const qty = reasons.reduce((s, r) => s + num(r.qty), 0);
  const billQty = bill ? num(bill.qty) : 0;
  const tooMuch = qty > billQty + 0.001;
  const ready = bill && total > 0 && !tooMuch && numberingOk(auto, own, ctx.note_numbers[kind]);
  const upd = <T extends { id: number }>(set: (f: (xs: T[]) => T[]) => void, id: number, patch: Partial<T>) =>
    set((xs) => xs.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  const nextId = (xs: { id: number }[]) => Math.max(0, ...xs.map((x) => x.id)) + 1;
  const partyNotes = ctx.notes[kind].filter((n) => key(n.party) === key(party));

  return (
    <>
      <p className="hint">{kind === "Purchase"
        ? "Reduces what we owe the supplier. Add one line per reason and any expenses the supplier bears (freight, unloading ...)."
        : "Reduces what the customer owes us. Add one line per reason and any expenses we bear for the customer."}</p>
      <div className="form-grid">
        <Numbering label="Note No." next={ctx.next[kind]} used={ctx.note_numbers[kind]} own={own} setOwn={setOwn}
          auto={auto} setAuto={setAuto} />
        {picker}
        <Field label="Note date" required><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
      </div>
      {!ctx.bills[kind].length && <div className="notice">There are no bills yet. Enter the invoice first.</div>}
      {bill && (
        <>
          <p className="hint">Bill: {bill.commodity} · {inr(bill.qty)} kg @ ₹{bill.rate} · GST {billGst}% · notes already on
            this bill: ₹ {fmtRate(num(bill.note))}</p>
          <h3>Reasons <span className="muted small">Leave the amount empty to use quantity × rate</span></h3>
          <table className="plain wide edit">
            <thead><tr><th>Reason</th><th className="num">Qty (kg)</th><th className="num">Rate (₹/kg)</th>
              <th className="num">Amount excl. GST</th><th className="num">GST %</th><th className="num">Total</th><th /></tr></thead>
            <tbody>
              {lines.map((r) => (
                <tr key={r.id}>
                  <td><Combo value={r.reason} onChange={(v) => upd(setReasons, r.id, { reason: v })} list="reason" options={ctx.lists.reason} /></td>
                  <td><Num value={r.qty} onChange={(v) => upd(setReasons, r.id, { qty: v })} /></td>
                  <td><Num value={r.rate} onChange={(v) => upd(setReasons, r.id, { rate: v })} /></td>
                  <td><Num value={r.amount} placeholder={r.value ? fmtRate(r.value) : ""} onChange={(v) => upd(setReasons, r.id, { amount: v })} /></td>
                  <td><Num value={r.gst} onChange={(v) => upd(setReasons, r.id, { gst: v })} step={0.5} /></td>
                  <td className="num">{fmtRate(r.total)}</td>
                  <td><button className="link" onClick={() => setReasons((xs) => xs.filter((x) => x.id !== r.id))}>Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="link" onClick={() => setReasons((xs) => [...xs, { id: nextId(xs), reason: ctx.lists.reason[0],
            qty: "", rate: billRate, amount: "", gst: billGst }])}>+ Add a reason</button>
          <h3>Expenses <span className="muted small">{kind === "Purchase" ? "the supplier bears" : "we bear for the customer"} (no GST)</span></h3>
          {expenses.length > 0 && (
            <table className="plain wide edit">
              <thead><tr><th>Expense</th><th className="num">Amount (₹)</th><th /></tr></thead>
              <tbody>
                {expenses.map((e) => (
                  <tr key={e.id}>
                    <td><Combo value={e.type} onChange={(v) => upd(setExpenses, e.id, { type: v })} list="expense" options={ctx.lists.expense} /></td>
                    <td><Num value={e.amount} onChange={(v) => upd(setExpenses, e.id, { amount: v })} /></td>
                    <td><button className="link" onClick={() => setExpenses((xs) => xs.filter((x) => x.id !== e.id))}>Remove</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <button className="link" onClick={() => setExpenses((xs) => [...xs, { id: nextId(xs), type: ctx.lists.expense[0], amount: "" }])}>
            + Add an expense</button>
          <Preview>{name} total <b>{money2(total)}</b>{qty > 0 && <> · quantity {inr(qty)} kg</>}</Preview>
          {tooMuch && <div className="notice warn">Quantity {inr(qty)} kg is more than the {inr(billQty)} kg on the bill.</div>}
          <div className="actions">
            <button className="primary" disabled={!ready || busy} onClick={async () => {
              const ok = await save("note", {
                kind, row: bill.source_row, note_no: auto ? null : own.trim(), date,
                lines: lines.filter((l) => l.value > 0).map((l) => ({ reason: l.reason || "Other", qty: num(l.qty),
                  rate: num(l.qty) ? num(l.rate) : 0, taxable: l.value, gst_pct: num(l.gst) })),
                expenses: expenses.filter((e) => num(e.amount) > 0).map((e) => ({ type: e.type || "Other", amount: num(e.amount) })),
              });
              if (ok) { setOwn(""); reset(); }
            }}>Save {name.toLowerCase()}</button>
          </div>
        </>
      )}
      {partyNotes.length > 0 && (
        <>
          <h3>{name}s for {party}</h3>
          <DataGrid rows={partyNotes} height="auto" search={false} cols={[["note_no", "Note No"], ["date", "Date", "date"],
            ["bill_no", "Bill"], ["reason", "Reason"], ["qty", "Qty (kg)", "qty"], ["taxable", "Value", "money"],
            ["gst", "GST", "money"], ["other", "Expense", "money"], ["total", "Total", "money"]]} />
        </>
      )}
    </>
  );
}

// --------------------------------------------------------------------------- ④ expenses on a bill
export function ExpenseForm({ ctx, save, busy }: FormProps) {
  const [kind, setKind] = useState<Side>("Purchase");
  return <ExpenseInner key={kind} ctx={ctx} save={save} busy={busy} kind={kind} setKind={setKind} />;
}

function ExpenseInner({ ctx, save, busy, kind, setKind }: FormProps & { kind: Side; setKind: (k: Side) => void }) {
  const { bill, picker } = useBill(ctx, kind);
  const [vals, setVals] = useState<Record<string, string>>({});
  useEffect(() => {
    const v: Record<string, string> = {};
    Object.values(ctx.expense_fields[kind]).flat().forEach((f) => { v[f] = bill && bill[f] != null ? String(bill[f]) : ""; });
    setVals(v);
  }, [bill?.source_row, ctx.version]); // eslint-disable-line react-hooks/exhaustive-deps
  const changes = bill ? Object.fromEntries(Object.entries(vals)
    .filter(([f, v]) => Math.abs(num(v) - num(bill[f])) > 0.005).map(([f, v]) => [f, num(v)])) : {};
  const n = Object.keys(changes).length;
  return (
    <>
      <div className="form-grid">
        <Field label="Bill type">
          <select value={kind} onChange={(e) => setKind(e.target.value as Side)}>
            <option value="Purchase">Purchase bill</option>
            <option value="Sales">Sales bill</option>
          </select>
        </Field>
        {picker}
      </div>
      {kind === "Purchase" && <p className="hint">Pre-bill expenses and the discount are entered with the purchase invoice.</p>}
      {bill && Object.entries(ctx.expense_fields[kind]).map(([group, fields]) => (
        <div key={group}>
          <h3>{group}</h3>
          <div className="form-grid">
            {fields.map((f) => (
              <Field key={f} label={LABELS[f] ?? f}>
                <Num value={vals[f] ?? ""} onChange={(v) => setVals((x) => ({ ...x, [f]: v }))} step={100} />
              </Field>
            ))}
          </div>
        </div>
      ))}
      {n > 0 && <Preview>Will change: {Object.entries(changes).map(([f, v]) => `${LABELS[f] ?? f} → ${money2(v)}`).join(", ")}</Preview>}
      <div className="actions">
        <button className="primary" disabled={!bill || !n || busy}
          onClick={() => save("expenses", { kind, row: bill!.source_row, changes })}>Save expenses</button>
      </div>
    </>
  );
}

// --------------------------------------------------------------------------- ⑤ / ⑨ payments and receipts
interface Alloc { tick: boolean; amount: string; tds: string }

export function SettlementForm({ ctx, save, busy, kind }: FormProps & { kind: Side }) {
  const name = kind === "Purchase" ? "Payment" : "Receipt";
  const bills = ctx.outstanding[kind];
  const due = useMemo(() => {
    const m = new Map<string, number>();
    bills.forEach((b) => m.set(b.party, (m.get(b.party) ?? 0) + b.outstanding));
    return [...m.entries()].filter(([, v]) => v > 0.5).sort((a, b) => a[0].localeCompare(b[0]));
  }, [bills]);
  const [party, setParty] = useState("");
  const [date, setDate] = useState(today());
  const [amount, setAmount] = useState("");
  const [alloc, setAlloc] = useState<Record<number, Alloc>>({});
  const [advance, setAdvance] = useState(false);
  const mine = useMemo(() => bills.filter((b) => b.party === party)
    .sort((a, b) => String(a.bill_date ?? "").localeCompare(String(b.bill_date ?? ""))), [bills, party]);
  useEffect(() => { setAlloc({}); setAdvance(false); }, [party, ctx.version]);

  const oldestFirst = () => {
    let left = num(amount);
    const next: Record<number, Alloc> = {};
    mine.forEach((b) => {
      const take = Math.min(left, b.outstanding);
      left -= take;
      next[b.row] = { tick: take > 0, amount: take > 0 && take < b.outstanding - 0.005 ? String(round2(take)) : "", tds: "" };
    });
    setAlloc(next);
  };
  const rows = mine.map((b) => {
    const a = alloc[b.row] ?? { tick: false, amount: "", tds: "" };
    const tds = num(a.tds);
    let amt = num(a.amount);
    if (!amt && a.tick) amt = Math.max(b.outstanding - tds, 0);
    return { ...b, a, amt: round2(amt), tds };
  });
  const used = rows.filter((r) => r.amt || r.tds);
  const adjusted = used.reduce((s, r) => s + r.amt, 0);
  const balance = round2(num(amount) - adjusted);
  const problems: string[] = [];
  if (balance < -0.5) problems.push(`The ticked bills add up to ${money2(adjusted)}, more than the total ${money2(num(amount))}. Untick a bill or type a smaller amount.`);
  else if (balance > 0.5 && !advance) problems.push(`${money2(balance)} is not adjusted yet. Tick more bills, or keep it as advance.`);
  const over = used.filter((r) => r.amt + r.tds > r.outstanding + 1).map((r) => r.bill_no ?? "?");
  if (over.length && !advance) problems.push(`Bill ${over.join(", ")} would be paid more than outstanding.`);
  const set = (row: number, patch: Partial<Alloc>) =>
    setAlloc((x) => ({ ...x, [row]: { ...(x[row] ?? { tick: false, amount: "", tds: "" }), ...patch } }));

  if (!due.length) return <div className="notice good">Nothing outstanding.</div>;
  return (
    <>
      <p className="hint">Enter the total {name.toLowerCase()}, then tick the bills it is adjusted against. A ticked bill is
        cleared in full unless you type a smaller amount. TDS can be added per bill.</p>
      <div className="form-grid">
        <Field label="Party" required>
          <select value={party} onChange={(e) => setParty(e.target.value)}>
            <option value="">Choose party</option>
            {due.map(([p, v]) => <option key={p} value={p}>{p} (due ₹ {inr(v)})</option>)}
          </select>
        </Field>
        <Field label={`${name} date`} required><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label={`Total amount ${kind === "Purchase" ? "paid" : "received"} (₹)`} required>
          <Num value={amount} onChange={setAmount} step={1000} />
        </Field>
        <div className="field">
          <span className="field-label">&nbsp;</span>
          <span className="numbering">
            <button className="secondary" disabled={!party || !num(amount)} onClick={oldestFirst}>Adjust oldest first</button>
            <button className="link" onClick={() => setAlloc({})}>Clear</button>
          </span>
        </div>
      </div>
      {party && (
        <>
          <table className="plain wide edit">
            <thead><tr><th>Adjust</th><th>Bill No.</th><th>Bill date</th><th className="num">Days</th>
              <th className="num">Outstanding</th><th className="num">Amount to adjust</th><th className="num">TDS</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.row}>
                  <td><input type="checkbox" checked={r.a.tick} onChange={(e) => set(r.row, { tick: e.target.checked })} /></td>
                  <td>{r.bill_no}</td><td>{day(r.bill_date)}</td><td className="num">{r.days ?? ""}</td>
                  <td className="num">{fmtRate(r.outstanding)}</td>
                  <td><Num value={r.a.amount} placeholder={r.a.tick ? fmtRate(r.amt) : ""} onChange={(v) => set(r.row, { amount: v, tick: true })} /></td>
                  <td><Num value={r.a.tds} onChange={(v) => set(r.row, { tds: v })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="kpis three">
            <div className="kpi"><div className="kpi-label">Total {name.toLowerCase()}</div><div className="kpi-value">{money2(num(amount))}</div></div>
            <div className="kpi"><div className="kpi-label">Adjusted against bills</div><div className="kpi-value">{money2(adjusted)}</div></div>
            <div className="kpi"><div className="kpi-label">Balance</div><div className={`kpi-value ${Math.abs(balance) > 0.5 ? "bad" : "good"}`}>{money2(balance)}</div></div>
          </div>
          {balance > 0.5 && used.length > 0 && (
            <label className="check"><input type="checkbox" checked={advance} onChange={(e) => setAdvance(e.target.checked)} />
              Keep the balance {money2(balance)} as advance (it is added to bill {used[used.length - 1].bill_no})</label>
          )}
          {problems.map((p) => <div key={p} className="notice warn">{p}</div>)}
          <div className="actions">
            <button className="primary" disabled={busy || problems.length > 0 || !num(amount) || !used.length} onClick={async () => {
              const list = used.map((r) => ({ row: r.row, amount: r.amt, tds: r.tds, outstanding: r.outstanding }));
              if (advance && balance > 0) list[list.length - 1].amount = round2(list[list.length - 1].amount + balance);
              const ok = await save("settlement", { kind, date, allocations: list });
              if (ok) { setParty(""); setAmount(""); }
            }}>Save {name.toLowerCase()}</button>
          </div>
        </>
      )}
    </>
  );
}
