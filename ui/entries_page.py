"""Transactions page: enter the business flow and write it straight into the Master Sheet.

Purchase Order -> Purchase Invoice -> Debit Note -> Expenses -> Payment
-> Sales Order -> Sales Invoice -> Credit Note -> Receipt
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from mis_reports import reports as R
from mis_reports.entries import EXPENSE_FIELDS, EntryError, MasterFile, restore_latest_backup
from mis_reports.xlsx_edit import FileLockedError

from .common import inr, show_table

STEPS = ["Purchase Order", "Purchase Invoice", "Debit Note", "Expenses", "Payment",
         "Sales Order", "Sales Invoice", "Credit Note", "Receipt"]
NUMS = "①②③④⑤⑥⑦⑧⑨"

FIELD_LABELS = {
    "adhat": "Adhat", "amc": "AMC", "labour": "Labour", "transport_pre": "Transportation (pre-bill)",
    "wh_load": "WH Load", "bags": "Bags", "other_pre": "Other", "discount": "Discount", "vatav": "Vatav",
    "storage": "Storage", "brokerage": "Brokerage", "sampling": "Sampling", "repacking": "Repacking",
    "transport_post": "Transportation (post-bill)", "loading": "Loading / Unloading",
}


# --------------------------------------------------------------------------- small helpers
def _key(form: str, name: str) -> str:
    return f"{form}_{name}_{st.session_state.setdefault('nonce', {}).get(form, 0)}"


def _reset(form: str):
    st.session_state.setdefault("nonce", {})
    st.session_state["nonce"][form] = st.session_state["nonce"].get(form, 0) + 1


def _options(*series) -> list[str]:
    vals = set()
    for s in series:
        vals.update(str(v).strip() for v in pd.Series(s).dropna() if str(v).strip())
    return sorted(vals, key=str.lower)


def _pick(label, options, key, default=None, required=False, help=None):
    """Dropdown that also accepts a new value typed by the user."""
    opts = list(options)
    if default and default not in opts:
        opts = [default] + opts
    return st.selectbox(label + (" *" if required else ""), opts, index=opts.index(default) if default else None,
                        key=key, accept_new_options=True, placeholder="Choose or type a new one", help=help)


def _last_for(df: pd.DataFrame, col: str, value) -> dict:
    if not value or df.empty:
        return {}
    rows = df[df[col].astype(str).str.strip().str.lower() == str(value).strip().lower()]
    if rows.empty:
        return {}
    last = rows.iloc[-1]
    return {k: (None if pd.isna(v) else v) for k, v in last.items()}


def _save(form: str, fn, message: str):
    try:
        fn()
    except FileLockedError:
        st.error("🔒 The Master Sheet is open in Excel, so it can't be saved. Close it in Excel and "
                 "click Save again. Nothing you typed is lost.")
        return
    except EntryError as exc:
        st.error(f"⚠️ {exc}")
        return
    st.session_state["flash"] = message
    _reset(form)
    st.cache_data.clear()
    st.rerun()


def _bill_label(r) -> str:
    d = r.bill_date.strftime("%d-%b-%Y") if pd.notna(r.bill_date) else "no date"
    return f"Bill {r.bill_no or '-'} · {d} · {r.commodity} · ₹{inr(r.bill_amt if pd.notna(r.bill_amt) else r.amount)}"


def _order_label(r) -> str:
    return (f"Contract {r.contract_no} · {r.party} · {r.commodity} · balance {r.bal_qty_mt:g} MT "
            f"@ ₹{r.rate:g}/kg")


def _open_orders(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df[(df["status"].fillna("").str.lower() != "closed") & (df["bal_qty_mt"].fillna(0) > 0)]


# --------------------------------------------------------------------------- the page
def render(data, master: MasterFile, aliases: dict):
    st.title("Enter Transactions")
    st.markdown(f"<span class='hint'>Every entry is written straight into <b>{master.path.name}</b> "
                "(a backup copy is kept first). Reports update immediately.</span>", unsafe_allow_html=True)
    if msg := st.session_state.pop("flash", None):
        st.toast(msg)

    today = date.today()
    ledgers = {"Purchase": R.creditors(data, R.Filters(as_of=today, aliases=aliases)),
               "Sales": R.debtors(data, R.Filters(as_of=today, aliases=aliases))}

    step = st.segmented_control("Step", [f"{NUMS[i]} {s}" for i, s in enumerate(STEPS)], key="entry_step",
                                default=f"{NUMS[0]} {STEPS[0]}", label_visibility="collapsed")
    step = STEPS[[f"{NUMS[i]} {s}" for i, s in enumerate(STEPS)].index(step)] if step else STEPS[0]
    with st.container(border=True):
        if step == "Purchase Order":
            _order_form("PO", data, master)
        elif step == "Purchase Invoice":
            _invoice_form("Purchase", data, master)
        elif step == "Debit Note":
            _note_form("Purchase", data, master)
        elif step == "Expenses":
            _expense_form(data, master)
        elif step == "Payment":
            _settlement_form("Purchase", data, master, ledgers["Purchase"])
        elif step == "Sales Order":
            _order_form("SO", data, master)
        elif step == "Sales Invoice":
            _invoice_form("Sales", data, master)
        elif step == "Credit Note":
            _note_form("Sales", data, master)
        else:
            _settlement_form("Sales", data, master, ledgers["Sales"])

    st.divider()
    left, right = st.columns([3, 1])
    with left:
        st.subheader("Recent entries")
        log = master.read_log(15)
        if log:
            log = pd.DataFrame(log)
            log["Amount"] = pd.to_numeric(log["Amount"], errors="coerce")
            show_table(log, money=["Amount"])
        else:
            st.caption("Nothing entered from this screen yet.")
    with right:
        st.subheader("Undo")
        st.caption("Puts the Master Sheet back the way it was before the last save.")
        if st.button("↩️ Undo last entry", width="stretch"):
            st.session_state["confirm_undo"] = True
        if st.session_state.get("confirm_undo"):
            st.warning("Undo the last saved entry?")
            a, b = st.columns(2)
            if a.button("Yes, undo", type="primary"):
                st.session_state.pop("confirm_undo")
                try:
                    name = restore_latest_backup(master.path, master.backup_dir)
                except PermissionError:
                    st.error("🔒 Close the Master Sheet in Excel first.")
                    return
                if name:
                    master._log("Undo", "", "", "", 0, f"restored {name}")
                    st.session_state["flash"] = "Last entry undone."
                else:
                    st.session_state["flash"] = "There is nothing to undo."
                st.cache_data.clear()
                st.rerun()
            if b.button("Cancel"):
                st.session_state.pop("confirm_undo")
                st.rerun()


# --------------------------------------------------------------------------- ① / ⑥ orders
def _order_form(kind: str, data, master: MasterFile):
    side = "Purchase" if kind == "PO" else "Sales"
    df = data.po if kind == "PO" else data.so
    bills = data.purchase if kind == "PO" else data.sales
    f = f"order_{kind}"
    st.subheader(f"New {side} Order")
    c = st.columns(3)
    with c[0]:
        party = _pick("Party", _options(bills["party"], df.get("party")), _key(f, "party"), required=True)
    prev = _last_for(bills, "party", party)
    with c[1]:
        product = _pick("Product", _options(bills["commodity"], df.get("commodity")), _key(f, "product"),
                        required=True)
    with c[2]:
        broker = _pick("Broker", _options(bills["broker"], df.get("broker")), _key(f, f"broker_{party}"),
                       default=prev.get("broker"))
    c = st.columns(3)
    when = c[0].date_input("Order date *", date.today(), key=_key(f, "date"), format="DD/MM/YYYY")
    qty = c[1].number_input("Quantity (MT) *", min_value=0.0, step=1.0, key=_key(f, "qty"))
    rate = c[2].number_input("Rate (₹ per kg) *", min_value=0.0, step=0.25, key=_key(f, "rate"))
    c = st.columns(3)
    delivery = c[0].date_input("Delivery date", None, key=_key(f, "delivery"), format="DD/MM/YYYY")
    with st.expander("More details (optional)"):
        c = st.columns(3)
        place = c[0].text_input("Delivery place", key=_key(f, "place"))
        packing = c[1].text_input("Packing", key=_key(f, "packing"))
        with c[2]:
            company = _pick("Company", _options(bills["company"]), _key(f, "company"),
                            default=prev.get("company") or (_options(bills["company"]) or [None])[0])
        c = st.columns(3)
        with c[0]:
            warehouse = _pick("Warehouse", _options(bills["warehouse"]), _key(f, "wh"))
        branch = c[1].text_input("Branch", value=prev.get("branch") or "", key=_key(f, "branch"))
    st.markdown(f"<div class='preview'>Order value: <b>₹ {inr(qty * 1000 * rate)}</b> "
                f"({qty:g} MT × 1000 × ₹{rate:g}/kg)</div>", unsafe_allow_html=True)
    if st.button(f"💾 Save {side} Order", type="primary", key=_key(f, "save")):
        fields = {"date": when, "party": party, "broker": broker, "commodity": product, "qty_mt": qty,
                  "rate": rate, "delivery_date": delivery, "delivery_place": place, "packing": packing,
                  "company": company, "warehouse": warehouse, "branch": branch}
        _save(f, lambda: master.add_order(kind, fields), f"✅ {side} Order saved for {party}.")

    st.markdown(f"#### Open {side.lower()} orders")
    open_ = _open_orders(df)
    if open_.empty:
        st.caption("No open orders.")
    else:
        v = open_[["contract_no", "date", "party", "commodity", "qty_mt", "bal_qty_mt", "rate", "amount"]]
        v = v.rename(columns={"contract_no": "Contract", "date": "Date", "party": "Party", "commodity": "Product",
                              "qty_mt": "Qty (MT)", "bal_qty_mt": "Balance (MT)", "rate": "Rate", "amount": "Balance ₹"})
        show_table(v, money=["Balance ₹"], rate=["Rate"], dates=["Date"])


# --------------------------------------------------------------------------- ② / ⑦ invoices
def _invoice_form(kind: str, data, master: MasterFile):
    purchase = kind == "Purchase"
    df = data.purchase if purchase else data.sales
    orders = _open_orders(data.po if purchase else data.so)
    f = f"inv_{kind}"
    st.subheader(f"New {kind} Invoice")

    link_opts = ["No order (direct invoice)"] + [_order_label(r) for r in orders.itertuples()]
    link = st.selectbox(f"Against {'purchase' if purchase else 'sales'} order", link_opts, key=_key(f, "link"))
    order = orders.iloc[link_opts.index(link) - 1] if link != link_opts[0] else None
    lk = f"{f}_{link_opts.index(link)}"   # widget keys change with the order so defaults refill

    c = st.columns(3)
    with c[0]:
        party = _pick("Party", _options(df["party"]), _key(lk, "party"), required=True,
                      default=order["party"] if order is not None else None)
    prev = _last_for(df, "party", party)
    pk = f"{lk}_{party}"   # party-dependent defaults refill when the party changes
    bill_no = c[1].text_input("Bill No." + (" " if purchase else " (our invoice no.)"), key=_key(lk, "bill_no"))
    bill_date = c[2].date_input("Bill date *", date.today(), key=_key(lk, "bill_date"), format="DD/MM/YYYY")

    c = st.columns(3)
    with c[0]:
        product = _pick("Product", _options(df["commodity"]), _key(lk, "product"), required=True,
                        default=_match(order["commodity"], df["commodity"]) if order is not None else None)
    qty = c[1].number_input("Weight (kg) *", min_value=0.0, step=10.0, key=_key(lk, "qty"),
                            value=float(order["bal_qty_mt"] * 1000) if order is not None else 0.0)
    rate = c[2].number_input("Rate (₹ per kg) *", min_value=0.0, step=0.25, key=_key(lk, "rate"),
                             value=float(order["rate"]) if order is not None else 0.0)
    c = st.columns(3)
    gst = c[0].number_input("GST %", min_value=0.0, max_value=28.0, step=0.5, key=_key(pk, "gst"),
                            value=5.0 if (prev.get("type") or "Local") != "Import" else 0.0)
    stock_date = c[1].date_input("WH in date" if purchase else "Delivery date", bill_date,
                                 key=_key(lk, "stock_date"), format="DD/MM/YYYY")
    truck = c[2].text_input("Truck No.", key=_key(lk, "truck"))

    with st.expander("More details (filled from this party's last bill - change if needed)"):
        c = st.columns(3)
        with c[0]:
            company = _pick("Company", _options(df["company"]), _key(pk, "company"),
                            default=prev.get("company") or (_options(df["company"]) or [None])[0])
        with c[1]:
            typ = _pick("Type", _options(df["type"]) or ["Local", "Import"], _key(pk, "type"),
                        default=prev.get("type") or "Local")
        with c[2]:
            sub = _pick("Sub Type", _options(df["sub_type"]), _key(pk, "sub"), default=prev.get("sub_type"))
        c = st.columns(3)
        with c[0]:
            broker = _pick("Broker", _options(df["broker"]), _key(pk, "broker"),
                           default=(order["broker"] if order is not None and pd.notna(order["broker"]) else None)
                           or prev.get("broker"))
        with c[1]:
            warehouse = _pick("Warehouse", _options(df["warehouse"]), _key(pk, "wh"), default=prev.get("warehouse"))
        gstin = c[2].text_input("Party GSTIN", value=prev.get("gstin") or "", key=_key(pk, "gstin"))
        c = st.columns(3)
        branch = c[0].text_input("Branch", value=prev.get("branch") or "", key=_key(pk, "branch"))
        hsn = c[1].text_input("HSN code", value=str(_last_for(df, "commodity", product).get("hsn") or ""),
                              key=_key(lk, f"hsn_{product}"))
        bags = c[2].number_input("No. of bags", min_value=0, step=1, key=_key(lk, "bags"))
        bill_weight = st.number_input("Bill weight (kg) if different from weight", min_value=0.0, step=10.0,
                                      key=_key(lk, "bill_weight"))

    amount = qty * rate
    tax = amount * gst / 100
    st.markdown(f"<div class='preview'>Amount before GST <b>₹ {inr(amount, 2)}</b> &nbsp;+&nbsp; GST {gst:g}% "
                f"<b>₹ {inr(tax, 2)}</b> &nbsp;=&nbsp; Bill amount <b>₹ {inr(amount + tax, 2)}</b></div>",
                unsafe_allow_html=True)

    dup = bool(bill_no) and not df[(df["party"].astype(str).str.lower() == str(party or "").lower())
                                   & (df["bill_no"].astype(str) == str(bill_no))].empty
    ok_dup = True
    if dup:
        ok_dup = st.checkbox(f"⚠️ Bill {bill_no} already exists for {party}. Tick to save it again anyway.",
                             key=_key(lk, "dup"))
    if st.button(f"💾 Save {kind} Invoice", type="primary", key=_key(lk, "save"), disabled=not ok_dup):
        fields = {"company": company, "type": typ, "sub_type": sub, "warehouse": warehouse, "broker": broker,
                  "party": party, "gstin": gstin, "branch": branch, "bill_no": bill_no, "bill_date": bill_date,
                  "stock_date": stock_date, "truck_no": truck, "commodity": product, "hsn": hsn,
                  "no_of_bags": bags or None, "qty": qty, "rate": rate,
                  "bill_weight": bill_weight or qty}
        row = int(order["source_row"]) if order is not None else None
        _save(f, lambda: master.add_invoice(kind, fields, gst_pct=gst, order_row=row),
              f"✅ {kind} Invoice {bill_no or ''} saved for {party}"
              + (f" and order contract {order['contract_no']} updated." if order is not None else "."))


def _match(value, series):
    """Use the spelling already in the sheet for a product typed differently on the order."""
    for v in _options(series):
        if R.product_name(v) == R.product_name(value):
            return v
    return value


# --------------------------------------------------------------------------- ③ / ⑧ notes
def _choose_bill(kind: str, data, key_prefix: str):
    df = data.purchase if kind == "Purchase" else data.sales
    c = st.columns(2)
    with c[0]:
        party = st.selectbox("Party *", _options(df["party"]), index=None, key=_key(key_prefix, "party"),
                             placeholder="Choose party")
    if not party:
        return None
    bills = df[df["party"] == party].sort_values("bill_date", na_position="first")
    if bills.empty:
        c[1].info("No bills for this party.")
        return None
    labels = [_bill_label(r) for r in bills.itertuples()]
    with c[1]:
        pick = st.selectbox("Bill *", labels, index=len(labels) - 1, key=_key(key_prefix, f"bill_{party}"))
    return bills.iloc[labels.index(pick)]


def _note_form(kind: str, data, master: MasterFile):
    name = "Debit Note" if kind == "Purchase" else "Credit Note"
    f = f"note_{kind}"
    st.subheader(name)
    st.caption("Reduces what " + ("we owe the supplier" if kind == "Purchase" else "the customer owes us")
               + " on a bill (quality claim, weight shortage, rate difference ...).")
    bill = _choose_bill(kind, data, f)
    if bill is None:
        return
    current = bill["note"] if pd.notna(bill["note"]) else 0
    st.caption(f"Already on this bill: ₹ {inr(current, 2)}")
    amount = st.number_input(f"{name} amount (₹) *", min_value=0.0, step=100.0, key=_key(f, "amount"))
    if st.button(f"💾 Save {name}", type="primary", key=_key(f, "save")):
        _save(f, lambda: master.add_note(kind, int(bill["source_row"]), amount),
              f"✅ {name} of ₹ {inr(amount, 2)} saved on bill {bill['bill_no']} ({bill['party']}).")


# --------------------------------------------------------------------------- ④ expenses
def _expense_form(data, master: MasterFile):
    f = "exp"
    st.subheader("Expenses on a bill")
    kind = st.radio("Bill type", ["Purchase", "Sales"], horizontal=True, key=_key(f, "kind"),
                    format_func=lambda k: f"{k} bill")
    bill = _choose_bill(kind, data, f"{f}_{kind}")
    if bill is None:
        return
    changes = {}
    for group, fields in EXPENSE_FIELDS[kind].items():
        st.markdown(f"**{group}**")
        cols = st.columns(4)
        for i, fld in enumerate(fields):
            cur = float(bill[fld]) if fld in bill and pd.notna(bill[fld]) else 0.0
            v = cols[i % 4].number_input(FIELD_LABELS.get(fld, fld), min_value=0.0, value=cur, step=100.0,
                                         key=_key(f, f"{kind}_{int(bill['source_row'])}_{fld}"))
            if abs(v - cur) > 0.005:
                changes[fld] = v
    if changes:
        st.info("Will change: " + ", ".join(f"{FIELD_LABELS.get(k, k)} → ₹ {inr(v, 2)}" for k, v in changes.items()))
    if st.button("💾 Save expenses", type="primary", key=_key(f, "save"), disabled=not changes):
        _save(f, lambda: master.set_expenses(kind, int(bill["source_row"]), changes),
              f"✅ Expenses saved on bill {bill['bill_no']} ({bill['party']}).")


# --------------------------------------------------------------------------- ⑤ / ⑨ payments & receipts
def _settlement_form(kind: str, data, master: MasterFile, ledger: R.Ledger):
    name = "Payment" if kind == "Purchase" else "Receipt"
    f = f"settle_{kind}"
    st.subheader(f"{name} " + ("to supplier" if kind == "Purchase" else "from customer"))
    bills = ledger.bills[ledger.bills["source_row"].notna()]
    due = bills.groupby("party")["outstanding"].sum()
    parties = [p for p in due.index if due[p] > 0.5]
    if not parties:
        st.success("Nothing outstanding.")
        return
    c = st.columns(3)
    party = c[0].selectbox("Party *", sorted(parties, key=str.lower), index=None, key=_key(f, "party"),
                           placeholder="Choose party",
                           format_func=lambda p: f"{p}  (due ₹ {inr(due[p])})")
    if not party:
        return
    pb = bills[bills["party"] == party].reset_index(drop=True)
    total_due = float(pb["outstanding"].sum())
    when = c[1].date_input(f"{name} date *", date.today(), key=_key(f, "date"), format="DD/MM/YYYY")
    amount = c[2].number_input(f"Amount {'paid' if kind == 'Purchase' else 'received'} (₹) *", min_value=0.0,
                               value=round(total_due, 2), step=1000.0, key=_key(f, f"amt_{party}"))

    left = amount
    alloc = []
    for r in pb.itertuples():
        take = min(left, r.outstanding)
        left -= take
        alloc.append(round(take, 2))
    table = pd.DataFrame({"Row": pb["source_row"].astype(int), "Bill No.": pb["bill_no"].astype(str),
                          "Bill Date": pb["bill_date"], "Outstanding": pb["outstanding"].round(2),
                          f"{name} now": alloc, "TDS": 0.0})
    st.caption("Amount is spread over the oldest bills first. You can change the amounts or add TDS per bill.")
    edited = st.data_editor(
        table, hide_index=True, width="stretch", key=_key(f, f"alloc_{party}_{amount}"),
        disabled=["Row", "Bill No.", "Bill Date", "Outstanding"],
        column_config={"Row": st.column_config.NumberColumn("Sheet row", format="%d"),
                       "Bill Date": st.column_config.DateColumn(format="DD-MM-YYYY"),
                       "Outstanding": st.column_config.NumberColumn(format="%.2f"),
                       f"{name} now": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
                       "TDS": st.column_config.NumberColumn(min_value=0.0, format="%.2f")})
    spread = float(edited[f"{name} now"].sum())
    over = edited[edited[f"{name} now"] + edited["TDS"] > edited["Outstanding"] + 1]
    problems = []
    if amount > total_due + 1:
        problems.append(f"Amount is more than the total due (₹ {inr(total_due, 2)}).")
    if abs(spread - amount) > 0.5:
        problems.append(f"₹ {inr(spread, 2)} is spread over bills but the amount is ₹ {inr(amount, 2)}.")
    if not over.empty:
        problems.append("Bill(s) " + ", ".join(over["Bill No."]) + " would be paid more than outstanding.")
    for p in problems:
        st.warning(p)
    if st.button(f"💾 Save {name}", type="primary", key=_key(f, "save"), disabled=bool(problems) or amount <= 0):
        allocations = [(int(r["Row"]), float(r[f"{name} now"]), float(r["TDS"])) for _, r in edited.iterrows()]
        outstanding = {int(r["Row"]): float(r["Outstanding"]) for _, r in edited.iterrows()}
        _save(f, lambda: master.add_settlement(kind, when, allocations, outstanding),
              f"✅ {name} of ₹ {inr(amount, 2)} saved for {party}.")
