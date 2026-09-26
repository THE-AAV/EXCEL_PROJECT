"""Transactions page: enter the business flow and write it straight into the Master Sheet.

Purchase Order -> Purchase Invoice -> Debit Note -> Expenses -> Payment
-> Sales Order -> Sales Invoice -> Credit Note -> Receipt
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from mis_reports import reports as R
from mis_reports.entries import (EXPENSE_FIELDS, NOTE_EXPENSES, NOTE_REASONS, EntryError, MasterFile, split_by_value, next_number,
                                 restore_latest_backup)
from mis_reports.xlsx_edit import FileLockedError

from . import table_entry
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
    style = st.segmented_control("Entry style", ["📝 Form", "📊 Table (like Excel)"], key="entry_style",
                                 default="📝 Form", help="Form: one entry at a time with boxes and dropdowns. "
                                 "Table: type many rows in a grid, like Excel, and save them together.")
    if style == "📊 Table (like Excel)":
        with st.container(border=True):
            table_entry.render(step, data, master, ledgers)
        _footer(master)
        return
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
    _footer(master)


def _footer(master: MasterFile):
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
def _number_field(f: str, label: str, existing, first="1"):
    """Automatic number (next in the series) or one the user types. Returns None for automatic."""
    auto_no = next_number(list(existing), first)
    c = st.columns([2, 3])
    mode = c[0].radio(f"{label} numbering", ["Automatic", "Enter my own"], horizontal=True,
                      key=_key(f, "nummode"))
    if mode == "Automatic":
        c[1].text_input(label, value=str(auto_no), disabled=True, key=_key(f, "autono"),
                        help="The next number in the series is given when you save.")
        return None, True
    own = c[1].text_input(f"{label} *", key=_key(f, "ownno"), placeholder=f"e.g. {auto_no}")
    taken = bool(own.strip()) and own.strip().lower() in {str(v).strip().lower() for v in existing if pd.notna(v)}
    if taken:
        c[1].error(f"{own} is already used.")
    return own.strip() or None, bool(own.strip()) and not taken


def _order_form(kind: str, data, master: MasterFile):
    side = "Purchase" if kind == "PO" else "Sales"
    df = data.po if kind == "PO" else data.so
    bills = data.purchase if kind == "PO" else data.sales
    f = f"order_{kind}"
    st.subheader(f"New {side} Order")
    contract_no, number_ok = _number_field(f, "Contract No.", df["contract_no"] if len(df) else [])
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
    place = c[1].text_input("Delivery place", key=_key(f, "place"))
    packing = c[2].text_input("Packing", key=_key(f, "packing"))
    with st.expander("More details (optional)"):
        c = st.columns(3)
        with c[0]:
            company = _pick("Company", _options(bills["company"]), _key(f, "company"),
                            default=prev.get("company") or (_options(bills["company"]) or [None])[0])
        with c[1]:
            warehouse = _pick("Warehouse", _options(bills["warehouse"]), _key(f, "wh"))
        branch = c[2].text_input("Branch", value=prev.get("branch") or "", key=_key(f, f"branch_{party}"))
    st.markdown(f"<div class='preview'>Order value: <b>₹ {inr(qty * 1000 * rate)}</b> "
                f"({qty:g} MT × 1000 × ₹{rate:g}/kg)</div>", unsafe_allow_html=True)
    if st.button(f"💾 Save {side} Order", type="primary", key=_key(f, "save"), disabled=not number_ok):
        fields = {"date": when, "party": party, "broker": broker, "commodity": product, "qty_mt": qty,
                  "rate": rate, "delivery_date": delivery, "delivery_place": place, "packing": packing,
                  "company": company, "warehouse": warehouse, "branch": branch}
        _save(f, lambda: master.add_order(kind, fields, contract_no=contract_no),
              f"✅ {side} Order {contract_no or ''} saved for {party}.")

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
PRE_LABELS = {"adhat": "Adhat", "amc": "AMC", "labour": "Labour", "transport_pre": "Transportation",
              "wh_load": "WH Load", "bags": "Bags", "other_pre": "Other", "discount": "Discount (less)"}


def _purchase_bill_label(r) -> str:
    d = r.bill_date.strftime("%d-%b-%Y") if pd.notna(r.bill_date) else "no date"
    return f"Bill {r.bill_no or '-'} · {r.party} · {d} · {r.commodity} {r.qty:,.0f} kg @ ₹{r.rate:g}"


def _invoice_form(kind: str, data, master: MasterFile):
    purchase = kind == "Purchase"
    df = data.purchase if purchase else data.sales
    all_orders = _open_orders(data.po if purchase else data.so)
    f = f"inv_{kind}"
    st.subheader(f"New {kind} Invoice")
    st.caption("One bill can have several items - each item can be against a different "
               f"{'purchase' if purchase else 'sales'} contract." +
               ("" if purchase else " An item can also be linked to the purchase bill the goods came from."))

    # ---- bill header
    c = st.columns(3)
    with c[0]:
        party = _pick("Party", _options(df["party"], all_orders.get("party")), _key(f, "party"), required=True)
    prev = _last_for(df, "party", party)
    pk = f"{f}_{party}"   # party-dependent defaults refill when the party changes
    if purchase:
        bill_no = c[1].text_input("Supplier's bill No.", key=_key(f, "bill_no"))
    else:
        bill_no = c[1].text_input("Our invoice No.", value=str(next_number(list(df["bill_no"].dropna()), "1")),
                                  key=_key(f, "bill_no"), help="Next number in the series - change it if needed.")
    bill_date = c[2].date_input("Bill date *", date.today(), key=_key(f, "bill_date"), format="DD/MM/YYYY")
    c = st.columns(3)
    stock_date = c[0].date_input("WH in date" if purchase else "Delivery date", bill_date,
                                 key=_key(f, "stock_date"), format="DD/MM/YYYY")
    truck = c[1].text_input("Truck No.", key=_key(f, "truck"))
    gst_default = 5.0 if (prev.get("type") or "Local") != "Import" else 0.0
    gst_all = c[2].number_input("GST % (for all items)", min_value=0.0, max_value=28.0, step=0.5,
                                value=gst_default, key=_key(pk, "gst"))

    tab_names = ["🧾 Items"] + (["💰 Pre-bill expenses"] if purchase else []) + ["📋 More details"]
    tabs = st.tabs(tab_names)

    # ---- items
    orders = all_orders
    if party:
        mine = all_orders[all_orders["party"].astype(str).str.lower() == str(party).lower()]
        orders = mine if not mine.empty else all_orders
    order_labels = ["No contract"] + [_order_label(r) for r in orders.itertuples()]
    ids_key = _key(f, "ids")
    ids = st.session_state.setdefault(ids_key, [0])
    lines = []
    with tabs[0]:
        for pos, i in enumerate(ids):
            with st.container(border=True):
                top = st.columns([6, 1])
                top[0].markdown(f"**Item {pos + 1}**")
                if len(ids) > 1 and top[1].button("🗑 Remove", key=_key(f, f"rm_{i}")):
                    ids.remove(i)
                    st.rerun()
                link = st.selectbox("Against contract", order_labels, key=_key(f, f"order_{i}"))
                order = orders.iloc[order_labels.index(link) - 1] if link != order_labels[0] else None
                lk = f"{f}_{i}_{order_labels.index(link)}"   # refill defaults when the contract changes
                c = st.columns([3, 2, 2])
                with c[0]:
                    product = _pick("Product", _options(df["commodity"]), _key(lk, "product"), required=True,
                                    default=_match(order["commodity"], df["commodity"]) if order is not None else None)
                qty = c[1].number_input("Weight (kg) *", min_value=0.0, step=10.0, key=_key(lk, "qty"),
                                        value=float(order["bal_qty_mt"] * 1000) if order is not None else 0.0)
                rate = c[2].number_input("Rate (₹ per kg) *", min_value=0.0, step=0.25, key=_key(lk, "rate"),
                                         value=float(order["rate"]) if order is not None else 0.0)
                link_row = None
                if not purchase:
                    pb = data.purchase[data.purchase["qty"].fillna(0) > 0]
                    if product:
                        same = pb[pb["commodity"].map(R.product_name) == R.product_name(product)]
                        pb = same if not same.empty else pb
                    pb = pb.sort_values("bill_date", ascending=False, na_position="last").head(300)
                    plabels = ["Not linked"] + [_purchase_bill_label(r) for r in pb.itertuples()]
                    pl = st.selectbox("Linked purchase bill (optional)", plabels, key=_key(f, f"plink_{i}_{product}"),
                                      help="The purchase bill these goods came from. Used for the bill-wise "
                                           "margin report and noted on both bills.")
                    if pl != plabels[0]:
                        link_row = int(pb.iloc[plabels.index(pl) - 1]["source_row"])
                lines.append({"commodity": product, "qty": qty, "rate": rate, "gst_pct": gst_all,
                              "order_row": int(order["source_row"]) if order is not None else None,
                              "contract": order["contract_no"] if order is not None else "",
                              "link_row": link_row,
                              "hsn": _last_for(df, "commodity", product).get("hsn")})
        if st.button("➕ Add another item", key=_key(f, "add")):
            ids.append(max(ids) + 1)
            st.rerun()

    # ---- pre-bill expenses (purchase)
    expenses = {}
    if purchase:
        with tabs[1]:
            st.caption("Enter the totals for this bill. They are split over the items in proportion to their "
                       "value and added to the item cost (the discount is taken off).")
            c = st.columns(4)
            for n, (fld, label) in enumerate(PRE_LABELS.items()):
                v = c[n % 4].number_input(label, min_value=0.0, step=100.0, key=_key(f, f"pre_{fld}"))
                if v:
                    expenses[fld] = v

    # ---- more details
    with tabs[-1]:
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
            broker = _pick("Broker", _options(df["broker"]), _key(pk, "broker"), default=prev.get("broker"))
        with c[1]:
            warehouse = _pick("Warehouse", _options(df["warehouse"]), _key(pk, "wh"), default=prev.get("warehouse"))
        gstin = c[2].text_input("Party GSTIN", value=prev.get("gstin") or "", key=_key(pk, "gstin"))
        branch = st.text_input("Branch", value=prev.get("branch") or "", key=_key(pk, "branch"))

    # ---- preview
    values = [l["qty"] * l["rate"] for l in lines]
    shares = {k: split_by_value(v, values) for k, v in expenses.items()} if sum(values) else {}
    prev_rows = []
    for n, l in enumerate(lines):
        amount = values[n]
        extra = sum(v[n] for k, v in shares.items() if k != "discount") - (shares.get("discount") or [0] * len(lines))[n]
        tax_base = amount + extra if purchase else amount
        gst = tax_base * l["gst_pct"] / 100
        prev_rows.append({"Item": n + 1, "Product": l["commodity"] or "", "Contract": l["contract"],
                          "Weight (kg)": l["qty"], "Rate": l["rate"], "Amount": amount,
                          "Pre-bill exp. (net)": extra, "GST": gst, "Bill amount": amount + gst})
    pv = pd.DataFrame(prev_rows)
    if len(pv):
        st.markdown("**Bill preview**")
        show_table(pv, money=["Weight (kg)", "Amount", "Pre-bill exp. (net)", "GST", "Bill amount"], rate=["Rate"])
        st.markdown(f"<div class='preview'>Total amount <b>₹ {inr(pv['Amount'].sum(), 2)}</b> &nbsp;+&nbsp; GST "
                    f"<b>₹ {inr(pv['GST'].sum(), 2)}</b> &nbsp;=&nbsp; Bill total <b>₹ {inr(pv['Bill amount'].sum(), 2)}"
                    "</b></div>", unsafe_allow_html=True)

    dup = bool(bill_no) and not df[(df["party"].astype(str).str.lower() == str(party or "").lower())
                                   & (df["bill_no"].astype(str) == str(bill_no))].empty
    ok_dup = True
    if dup:
        ok_dup = st.checkbox(f"⚠️ Bill {bill_no} already exists for {party}. Tick to save it again anyway.",
                             key=_key(f, "dup"))
    if st.button(f"💾 Save {kind} Invoice", type="primary", key=_key(f, "save"), disabled=not ok_dup):
        header = {"company": company, "type": typ, "sub_type": sub, "warehouse": warehouse, "broker": broker,
                  "party": party, "gstin": gstin, "branch": branch, "bill_no": bill_no, "bill_date": bill_date,
                  "stock_date": stock_date, "truck_no": truck}
        items = [{k: v for k, v in l.items() if k != "contract"} for l in lines]
        _save(f, lambda: master.add_invoice_lines(kind, header, items, expenses),
              f"✅ {kind} Invoice {bill_no or ''} saved for {party} ({len(items)} item{'s' if len(items) > 1 else ''}).")


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
    register = data.debit_notes if kind == "Purchase" else data.credit_notes
    f = f"note_{kind}"
    st.subheader(name)
    st.caption(("Reduces what we owe the supplier. Add one line per reason (goods returned, weight shortage, "
                "quality claim, rate difference ...) and any expenses the supplier bears (freight, unloading ...).")
               if kind == "Purchase" else
               ("Reduces what the customer owes us. Add one line per reason (goods returned, weight shortage, "
                "quality claim, rate difference ...) and any expenses we bear for the customer."))
    note_no, number_ok = _number_field(f, "Note No.", register["note_no"] if len(register) else [],
                                       "DN-0001" if kind == "Purchase" else "CN-0001")
    bill = _choose_bill(kind, data, f)
    if bill is None:
        return
    bill_qty = float(bill["qty"]) if pd.notna(bill["qty"]) else 0.0
    bill_rate = float(bill["rate"]) if pd.notna(bill["rate"]) else 0.0
    base = bill["net_amount"] if kind == "Purchase" else bill["amount"]
    bill_gst = round(float(bill["gst"]) / float(base) * 200) / 2 if pd.notna(bill["gst"]) and base else 0.0
    st.markdown(f"<span class='hint'>Bill: {bill['commodity']} · {bill_qty:,.0f} kg @ ₹{bill_rate:g} · GST "
                f"{bill_gst:g}% · notes already on this bill: ₹ {inr(bill['note'] if pd.notna(bill['note']) else 0, 2)}"
                "</span>", unsafe_allow_html=True)
    bk = f"{f}_{int(bill['source_row'])}"   # tables refill when another bill is chosen
    when = st.date_input("Note date *", date.today(), key=_key(f, "date"), format="DD/MM/YYYY")

    st.markdown("**Reasons** - one line each. Leave *Amount* empty to use quantity × rate.")
    reasons = st.data_editor(
        pd.DataFrame([{"Reason": NOTE_REASONS[0], "Qty (kg)": None, "Rate (₹/kg)": bill_rate,
                       "Amount excl. GST (₹)": None, "GST %": bill_gst}]),
        num_rows="dynamic", hide_index=True, width="stretch", key=_key(bk, "reasons"),
        column_config={"Reason": st.column_config.SelectboxColumn(options=NOTE_REASONS, required=True),
                       "Qty (kg)": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
                       "Rate (₹/kg)": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
                       "Amount excl. GST (₹)": st.column_config.NumberColumn(min_value=0.0, format="%.2f"),
                       "GST %": st.column_config.NumberColumn(min_value=0.0, max_value=28.0, format="%.1f")})
    st.markdown("**Expenses** " + ("the supplier bears" if kind == "Purchase" else "we bear for the customer")
                + " (no GST) - one line each.")
    expenses = st.data_editor(
        pd.DataFrame([{"Expense": NOTE_EXPENSES[0], "Amount (₹)": None}]), num_rows="dynamic", hide_index=True,
        width="stretch", key=_key(bk, "expenses"),
        column_config={"Expense": st.column_config.SelectboxColumn(options=NOTE_EXPENSES, required=True),
                       "Amount (₹)": st.column_config.NumberColumn(min_value=0.0, format="%.2f")})

    lines, preview = [], []
    for _, r in reasons.iterrows():
        qty = _f(r["Qty (kg)"])
        rate = _f(r["Rate (₹/kg)"])
        amount = _f(r["Amount excl. GST (₹)"]) or round(qty * rate, 2)
        if not amount:
            continue
        gst = round(amount * _f(r["GST %"]) / 100, 2)
        lines.append({"reason": r["Reason"], "qty": qty, "rate": rate if qty else 0, "taxable": amount,
                      "gst_pct": _f(r["GST %"])})
        preview.append({"Line": r["Reason"], "Qty (kg)": qty, "Value": amount, "GST": gst, "Total": amount + gst})
    ex = []
    for _, r in expenses.iterrows():
        if _f(r["Amount (₹)"]):
            ex.append({"type": r["Expense"], "amount": _f(r["Amount (₹)"])})
            preview.append({"Line": f"Expense: {r['Expense']}", "Qty (kg)": 0.0, "Value": 0.0, "GST": 0.0,
                            "Total": _f(r["Amount (₹)"])})
    total = sum(p["Total"] for p in preview)
    qty_total = sum(p["Qty (kg)"] for p in preview)
    if preview:
        show_table(pd.DataFrame(preview), money=["Qty (kg)", "Value", "GST", "Total"])
    st.markdown(f"<div class='preview'>{name} total <b>₹ {inr(total, 2)}</b>"
                + (f" · quantity {qty_total:,.2f} kg" if qty_total else "") + "</div>", unsafe_allow_html=True)
    if qty_total > bill_qty + 0.001:
        st.warning(f"Quantity {qty_total:,.2f} kg is more than the {bill_qty:,.2f} kg on the bill.")
    if st.button(f"💾 Save {name}", type="primary", key=_key(f, "save"),
                 disabled=not number_ok or total <= 0 or qty_total > bill_qty + 0.001):
        note = {"note_no": note_no, "date": when, "lines": lines, "expenses": ex}
        _save(f, lambda: master.add_note_detailed(kind, int(bill["source_row"]), note),
              f"✅ {name} of ₹ {inr(total, 2)} saved on bill {bill['bill_no']} ({bill['party']}).")

    party_notes = register[register["party"] == bill["party"]] if len(register) else register
    if len(party_notes):
        st.markdown(f"#### {name}s for {bill['party']}")
        v = party_notes[["note_no", "date", "bill_no", "reason", "qty", "taxable", "gst", "other", "total"]]
        show_table(v.rename(columns={"note_no": "Note No", "date": "Date", "bill_no": "Bill", "reason": "Reason",
                                     "qty": "Qty (kg)", "taxable": "Value", "gst": "GST", "other": "Expense",
                                     "total": "Total"}),
                   money=["Qty (kg)", "Value", "GST", "Expense", "Total"], dates=["Date"])


def _f(v) -> float:
    try:
        v = float(v)
        return 0.0 if v != v else v
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- ④ expenses
def _expense_form(data, master: MasterFile):
    f = "exp"
    st.subheader("Expenses on a bill")
    kind = st.radio("Bill type", ["Purchase", "Sales"], horizontal=True, key=_key(f, "kind"),
                    format_func=lambda k: f"{k} bill")
    if kind == "Purchase":
        st.caption("Storage, brokerage and other expenses after the bill, and Vatav. Pre-bill expenses and discount "
                   "are entered on the purchase invoice (② Purchase Invoice → 💰 Pre-bill expenses).")
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
    st.caption(f"Enter the total {name.lower()}, then tick the invoices it is adjusted against. Ticked invoices "
               "are cleared in full unless you type a smaller amount. You can also add TDS per invoice.")
    bills = ledger.bills[ledger.bills["source_row"].notna()]
    due = bills.groupby("party")["outstanding"].sum()
    parties = [p for p in due.index if due[p] > 0.5]
    if not parties:
        st.success("Nothing outstanding.")
        return
    c = st.columns(3)
    party = c[0].selectbox("Party *", sorted(parties, key=str.lower), index=None, key=_key(f, "party"),
                           placeholder="Choose party", format_func=lambda p: f"{p}  (due ₹ {inr(due[p])})")
    if not party:
        return
    pb = bills[bills["party"] == party].sort_values("bill_date", na_position="first").reset_index(drop=True)
    total_due = float(pb["outstanding"].sum())
    when = c[1].date_input(f"{name} date *", date.today(), key=_key(f, "date"), format="DD/MM/YYYY")
    amount = c[2].number_input(f"Total amount {'paid' if kind == 'Purchase' else 'received'} (₹) *",
                               min_value=0.0, value=0.0, step=1000.0, key=_key(f, f"amt_{party}"),
                               help=f"Total due from the invoices below: ₹ {inr(total_due, 2)}")
    auto_key = f"{f}_auto_{party}"
    b = st.columns([1, 1, 3])
    if b[0].button("↻ Adjust oldest first", key=_key(f, "auto"), help="Tick the oldest invoices until the total "
                   "amount is used up"):
        st.session_state[auto_key] = st.session_state.get(auto_key, 0) + 1
    if b[1].button("✖ Clear ticks", key=_key(f, "clear")):
        st.session_state[auto_key] = -abs(st.session_state.get(auto_key, 0)) - 1
    auto = st.session_state.get(auto_key, 0)
    left, ticks, amounts = amount, [], []
    for r in pb.itertuples():
        take = min(left, r.outstanding) if auto > 0 else 0.0
        left -= take
        ticks.append(take > 0)
        amounts.append(round(take, 2) if take and take < r.outstanding - 0.005 else None)
    table = pd.DataFrame({"Adjust": ticks, "Bill No.": pb["bill_no"].astype(str), "Bill Date": pb["bill_date"],
                          "Days": pb["days"], "Outstanding": pb["outstanding"].round(2),
                          "Amount to adjust": amounts, "TDS": [None] * len(pb)})
    edited = st.data_editor(
        table, hide_index=True, width="stretch", key=_key(f, f"alloc_{party}_{auto}_{amount if auto > 0 else ''}"),
        disabled=["Bill No.", "Bill Date", "Days", "Outstanding"],
        column_config={"Adjust": st.column_config.CheckboxColumn("✓ Adjust"),
                       "Bill Date": st.column_config.DateColumn(format="DD-MM-YYYY"),
                       "Days": st.column_config.NumberColumn(format="%d"),
                       "Outstanding": st.column_config.NumberColumn(format="%.2f"),
                       "Amount to adjust": st.column_config.NumberColumn(
                           min_value=0.0, format="%.2f", help="Leave empty to clear the invoice in full"),
                       "TDS": st.column_config.NumberColumn(min_value=0.0, format="%.2f")})
    alloc = []
    for i, r in edited.iterrows():
        tds = _f(r["TDS"])
        amt = _f(r["Amount to adjust"])
        if not amt and bool(r["Adjust"]):
            amt = max(float(r["Outstanding"]) - tds, 0.0)
        if amt or tds:
            alloc.append({"row": int(pb.loc[i, "source_row"]), "bill": r["Bill No."], "amount": round(amt, 2),
                          "tds": tds, "outstanding": float(r["Outstanding"])})
    adjusted = sum(a["amount"] for a in alloc)
    balance = round(amount - adjusted, 2)
    m = st.columns(3)
    m[0].metric(f"Total {name.lower()}", f"₹ {inr(amount, 2)}")
    m[1].metric("Adjusted against invoices", f"₹ {inr(adjusted, 2)}")
    m[2].metric("Balance", f"₹ {inr(balance, 2)}")
    problems = []
    advance = False
    if balance < -0.5:
        problems.append(f"Invoices ticked add up to ₹ {inr(adjusted, 2)}, more than the total ₹ {inr(amount, 2)}. "
                        "Untick an invoice or type a smaller amount.")
    elif balance > 0.5:
        if alloc:
            advance = st.checkbox(f"Keep the balance ₹ {inr(balance, 2)} as advance (on account) - it is added to "
                                  f"invoice {alloc[-1]['bill']}", key=_key(f, "advance"))
        if not advance:
            problems.append(f"₹ {inr(balance, 2)} is not adjusted yet. Tick more invoices, or keep it as advance.")
    over = [a["bill"] for a in alloc if a["amount"] + a["tds"] > a["outstanding"] + 1]
    if over and not advance:
        problems.append("Invoice(s) " + ", ".join(over) + " would be paid more than outstanding.")
    for p in problems:
        st.warning(p)
    if st.button(f"💾 Save {name}", type="primary", key=_key(f, "save"),
                 disabled=bool(problems) or amount <= 0 or not alloc):
        if advance and balance > 0:
            alloc[-1]["amount"] = round(alloc[-1]["amount"] + balance, 2)
        allocations = [(a["row"], a["amount"], a["tds"]) for a in alloc]
        outstanding = {a["row"]: a["outstanding"] for a in alloc}
        _save(f, lambda: master.add_settlement(kind, when, allocations, outstanding),
              f"✅ {name} of ₹ {inr(amount, 2)} saved for {party} against {len(alloc)} invoice(s).")
