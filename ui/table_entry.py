"""'Table (like Excel)' entry style: type many rows into a grid and save them together.

Every section of the Enter Transactions page has one. All rows of one save go into the Master Sheet
together (or none, if any row has a problem), and one Undo takes them all back out.
"""
from __future__ import annotations

import re
from datetime import date

import pandas as pd
import streamlit as st

from mis_reports import reports as R
from mis_reports.entries import EXPENSE_FIELDS, NOTE_EXPENSES, NOTE_REASONS, EntryError, MasterFile, next_number
from mis_reports.xlsx_edit import FileLockedError

from . import choices
from .common import inr, show_table

CC = st.column_config
EMPTY_ROWS = 5
EXPENSE_PREFIX = "Expense - "
PRE_BILL_COLS = {"Adhat": "adhat", "AMC": "amc", "Labour": "labour", "Transport": "transport_pre",
                 "WH Load": "wh_load", "Bags": "bags", "Other exp.": "other_pre", "Discount": "discount"}
FIELD_LABELS = {"adhat": "Adhat", "amc": "AMC", "labour": "Labour", "transport_pre": "Transportation",
                "wh_load": "WH Load", "bags": "Bags", "other_pre": "Other", "discount": "Discount", "vatav": "Vatav",
                "storage": "Storage", "brokerage": "Brokerage", "sampling": "Sampling", "repacking": "Repacking",
                "transport_post": "Transportation", "loading": "Loading / Unloading"}


# --------------------------------------------------------------------------- helpers
def _nonce(key: str) -> int:
    return st.session_state.setdefault("table_nonce", {}).get(key, 0)


def _bump(key: str):
    st.session_state.setdefault("table_nonce", {})[key] = _nonce(key) + 1


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and not v.strip()) or v is pd.NaT


def _num(v) -> float:
    try:
        v = float(v)
        return 0.0 if v != v else v
    except (TypeError, ValueError):
        return 0.0


def _day(v):
    if _blank(v):
        return None
    return pd.Timestamp(v).date()


def _txt(v) -> str:
    if _blank(v):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


class Names:
    """Matches what is typed to the spelling already in the sheet (capital letters and spaces ignored)."""

    def __init__(self, *series):
        self.known = {}
        for s in series:
            for v in pd.Series(s).dropna():
                self.known.setdefault(self.key(v), str(v).strip())
        self.new = set()

    @staticmethod
    def key(v) -> str:
        return re.sub(r"\s+", " ", str(v)).strip().lower()

    def __call__(self, v) -> str:
        t = _txt(v)
        if not t:
            return ""
        if self.key(t) in self.known:
            return self.known[self.key(t)]
        self.new.add(t)
        return t


def _grid(key: str, df: pd.DataFrame, config: dict, help_text: str, disabled=()):
    st.caption(help_text + " Click a cell and type, as in Excel. Use the ➕ under the table (or Tab past the last "
               "row) for more rows; tick rows on the left and press Delete to remove them. Copy / paste from "
               "Excel works too.")
    return st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", column_config=config,
                          key=f"{key}_{_nonce(key)}", disabled=list(disabled))


def _free(key: str) -> bool:
    return st.toggle("✍️ Type names freely", key=f"{key}_free",
                     help="Name columns are dropdowns of the names in the sheet plus any you add with ➕ above. "
                          "Turn this on to type or paste names straight into the cells instead, e.g. a block "
                          "copied from Excel with new names in it.")


def _name_col(field: str, free: bool, *series, **kw):
    """A dropdown of known names (sheet + added this session), or a plain text column when typing freely."""
    if free:
        return CC.TextColumn(**kw)
    return CC.SelectboxColumn(options=choices.options(field, *series), **kw)


def _party_defaults(*frames) -> "callable":
    """Returns f(party) -> the party's latest row (as a dict) in the first frame that has one."""
    def last(party):
        for df in frames:
            if df is None or df.empty or not party:
                continue
            rows = df[df["party"].astype(str).str.strip().str.lower() == str(party).strip().lower()]
            if len(rows):
                return {k: v for k, v in rows.iloc[-1].items() if not _blank(v)}
        return {}
    return last


def _save_rows(key: str, master: MasterFile, work: list, what: str, names: list[Names] = (), problems=()):
    """work: [(row label, callable)] run inside one batch. Any problems block the save."""
    new = sorted({n for nm in names for n in nm.new})
    if new:
        st.info("New names (not in the sheet yet): " + ", ".join(new))
    for p in problems:
        st.warning(p)
    st.markdown(f"**{len(work)} {what} ready to save.**" if work else "*Nothing to save yet - fill in the table.*")
    c = st.columns([1, 1, 3])
    if c[0].button("💾 Save all rows", type="primary", key=f"{key}_save", disabled=not work or bool(problems)):
        try:
            with master.batch():
                for label, fn in work:
                    try:
                        fn()
                    except EntryError as exc:
                        raise EntryError(f"{label}: {exc}") from None
        except FileLockedError:
            st.error("🔒 The Master Sheet is open in Excel, so it can't be saved. Close it in Excel and click "
                     "Save again. Nothing you typed is lost.")
            return
        except EntryError as exc:
            st.error(f"⚠️ Nothing was saved. {exc}")
            return
        st.session_state["flash"] = f"✅ {len(work)} {what} saved."
        _bump(key)
        st.cache_data.clear()
        st.rerun()
    if c[1].button("✖ Clear table", key=f"{key}_clear"):
        _bump(key)
        st.rerun()


def _open_orders(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df[(df["status"].fillna("").str.lower() != "closed") & (df["bal_qty_mt"].fillna(0) > 0)]


def _order_labels(orders: pd.DataFrame) -> dict[str, pd.Series]:
    return {f"{r['contract_no']} · {r['party']} · {r['commodity']} · bal {r['bal_qty_mt']:g} MT @ {r['rate']:g}": r
            for _, r in orders.iterrows()}


def _bill_labels(df: pd.DataFrame) -> dict[str, pd.Series]:
    out = {}
    for _, r in df.sort_values("bill_date", ascending=False, na_position="last").iterrows():
        d = r["bill_date"].strftime("%d-%m-%y") if pd.notna(r["bill_date"]) else "no date"
        out[f"{r['party']} · Bill {_txt(r['bill_no']) or '-'} · {r['commodity']} · {d} · row {int(r['source_row'])}"] = r
    return out


# --------------------------------------------------------------------------- the dispatcher
def render(step: str, data, master: MasterFile, ledgers: dict):
    if step in ("Purchase Order", "Sales Order"):
        _orders("PO" if step == "Purchase Order" else "SO", data, master)
    elif step in ("Purchase Invoice", "Sales Invoice"):
        _invoices("Purchase" if step == "Purchase Invoice" else "Sales", data, master)
    elif step in ("Debit Note", "Credit Note"):
        _notes("Purchase" if step == "Debit Note" else "Sales", data, master)
    elif step == "Expenses":
        _expenses(data, master)
    else:
        kind = "Purchase" if step == "Payment" else "Sales"
        _settlements(kind, master, ledgers[kind])


# --------------------------------------------------------------------------- ① / ⑥ orders
def _orders(kind: str, data, master: MasterFile):
    side = "Purchase" if kind == "PO" else "Sales"
    key = f"tbl_{kind}"
    df, bills = (data.po, data.purchase) if kind == "PO" else (data.so, data.sales)
    st.subheader(f"{side} Orders - table")
    pf = f"party:{side}"
    choices.add_new_box(key, {pf: (bills["party"], df.get("party")), "product": (bills["commodity"], df.get("commodity")),
                              "broker": (bills["broker"], df.get("broker")), "place": (df.get("delivery_place"),),
                              "packing": (df.get("packing"),), "company": (bills["company"], df.get("company")),
                              "warehouse": (bills["warehouse"], df.get("warehouse")),
                              "branch": (bills["branch"], df.get("branch"))})
    free = _free(key)
    n = EMPTY_ROWS
    start = pd.DataFrame({"Contract No": [""] * n, "Date": [date.today()] * n, "Party": [None] * n,
                          "Product": [None] * n, "Qty (MT)": [None] * n, "Rate (₹/kg)": [None] * n,
                          "Broker": [None] * n, "Delivery Date": [None] * n, "Delivery Place": [None] * n,
                          "Packing": [None] * n, "Company": [None] * n, "Warehouse": [None] * n, "Branch": [None] * n})
    party_hint = "Empty = the party's usual"
    grid = _grid(key, start, {
        "Contract No": CC.TextColumn(help="Leave empty to number it automatically"),
        "Date": CC.DateColumn(format="DD-MM-YYYY", required=True),
        "Party": _name_col(pf, free, bills["party"], df.get("party"), width="medium"),
        "Product": _name_col("product", free, bills["commodity"], df.get("commodity"), width="medium"),
        "Qty (MT)": CC.NumberColumn(min_value=0.0, format="%.3f"),
        "Rate (₹/kg)": CC.NumberColumn(min_value=0.0, format="%.2f"),
        "Broker": _name_col("broker", free, bills["broker"], df.get("broker"), help=party_hint),
        "Delivery Date": CC.DateColumn(format="DD-MM-YYYY"),
        "Delivery Place": _name_col("place", free, df.get("delivery_place")),
        "Packing": _name_col("packing", free, df.get("packing")),
        "Company": _name_col("company", free, bills["company"], df.get("company"), help=party_hint),
        "Warehouse": _name_col("warehouse", free, bills["warehouse"], df.get("warehouse"), help=party_hint),
        "Branch": _name_col("branch", free, bills["branch"], df.get("branch"), help=party_hint)},
        "One row per contract. Contract No. is given automatically when left empty. Broker, company, warehouse "
        "and branch left empty are filled in with the party's usual ones.")
    parties = Names(bills["party"], df.get("party"))
    products = Names(bills["commodity"], df.get("commodity"))
    brokers = Names(bills["broker"], df.get("broker"))
    companies = Names(bills["company"], df.get("company"))
    warehouses = Names(bills["warehouse"], df.get("warehouse"))
    usual = _party_defaults(bills, df)
    first_company = (choices.options(None, bills["company"], df.get("company")) or [""])[0]
    work, preview = [], []
    for i, r in grid.iterrows():
        if all(_blank(r[c]) for c in ("Party", "Product", "Qty (MT)", "Rate (₹/kg)")):
            continue
        party = parties(r["Party"])
        prev = usual(party)
        fields = {"date": _day(r["Date"]), "party": party, "commodity": products(r["Product"]),
                  "qty_mt": _num(r["Qty (MT)"]), "rate": _num(r["Rate (₹/kg)"]),
                  "broker": brokers(r["Broker"]) or _txt(prev.get("broker")),
                  "delivery_date": _day(r["Delivery Date"]), "delivery_place": _txt(r["Delivery Place"]),
                  "packing": _txt(r["Packing"]),
                  "company": companies(r["Company"]) or _txt(prev.get("company")) or first_company,
                  "warehouse": warehouses(r["Warehouse"]) or _txt(prev.get("warehouse")),
                  "branch": _txt(r["Branch"]) or _txt(prev.get("branch"))}
        no = _txt(r["Contract No"]) or None
        preview.append({"Row": i + 1, "Contract": no or "(automatic)", "Party": party, "Product": fields["commodity"],
                        "Broker": fields["broker"], "Company": fields["company"], "Warehouse": fields["warehouse"],
                        "Branch": fields["branch"], "Value ₹": fields["qty_mt"] * 1000 * fields["rate"]})
        work.append((f"Row {i + 1}", lambda fields=fields, no=no: master.add_order(kind, fields, contract_no=no)))
    if preview:
        st.markdown("**Orders to be saved** (with the party's usual details filled in)")
        show_table(pd.DataFrame(preview), money=["Value ₹"])
    _save_rows(key, master, work, f"{side.lower()} order(s)", [parties, products, brokers, companies, warehouses])


# --------------------------------------------------------------------------- ② / ⑦ invoices
def _invoices(kind: str, data, master: MasterFile):
    purchase = kind == "Purchase"
    key = f"tbl_inv_{kind}"
    df = data.purchase if purchase else data.sales
    open_orders = _open_orders(data.po if purchase else data.so)
    orders = _order_labels(open_orders)
    st.subheader(f"{kind} Invoices - table")
    pf = f"party:{kind}"
    choices.add_new_box(key, {pf: (df["party"], open_orders.get("party")), "product": (df["commodity"],),
                              "broker": (df["broker"],), "warehouse": (df["warehouse"],), "company": (df["company"],),
                              "type": (df["type"], ["Local", "Import"]), "sub_type": (df["sub_type"],),
                              "branch": (df["branch"],)})
    free = _free(key)
    usual_hint = "Empty = the party's usual"
    stock_col = "WH In Date" if purchase else "Delivery Date"
    n = EMPTY_ROWS
    cols = {"Bill No": [""] * n, "Bill Date": [date.today()] * n, "Party": [None] * n, "Product": [None] * n,
            "Weight (kg)": [None] * n, "Rate (₹/kg)": [None] * n, "GST %": [None] * n, "Against contract": [None] * n}
    config = {"Bill No": CC.TextColumn(help="Rows with the same party, bill no. and date form one bill"
                                       + ("" if purchase else ". Leave empty to number it automatically")),
              "Bill Date": CC.DateColumn(format="DD-MM-YYYY", required=True),
              "Party": _name_col(pf, free, df["party"], open_orders.get("party"), width="medium",
                                 help="Empty = the contract's party"),
              "Product": _name_col("product", free, df["commodity"], width="medium",
                                   help="Empty = the contract's product"),
              "Weight (kg)": CC.NumberColumn(min_value=0.0, format="%.2f", help="Empty = the contract's balance"),
              "Rate (₹/kg)": CC.NumberColumn(min_value=0.0, format="%.4f", help="Empty = the contract's rate"),
              "GST %": CC.NumberColumn(min_value=0.0, max_value=28.0, format="%.1f",
                                       help="Empty = 5% (0% when the type is Import)"),
              "Against contract": CC.SelectboxColumn(options=list(orders), width="large"),
              stock_col: CC.DateColumn(format="DD-MM-YYYY", help="Empty = the bill date")}
    links = {}
    if not purchase:
        links = _bill_labels(data.purchase[data.purchase["qty"].fillna(0) > 0])
        cols["Linked purchase bill"] = [None] * n
        config["Linked purchase bill"] = CC.SelectboxColumn(options=list(links), width="large")
    cols.update({"Truck No": [""] * n, stock_col: [None] * n, "Type": [None] * n, "Sub Type": [None] * n,
                 "Broker": [None] * n, "Warehouse": [None] * n, "Company": [None] * n, "Party GSTIN": [""] * n,
                 "Branch": [None] * n})
    config.update({
        "Type": _name_col("type", free, df["type"], ["Local", "Import"], help=usual_hint + " (else Local)"),
        "Sub Type": _name_col("sub_type", free, df["sub_type"], help=usual_hint),
        "Broker": _name_col("broker", free, df["broker"], help=usual_hint),
        "Warehouse": _name_col("warehouse", free, df["warehouse"], help=usual_hint),
        "Company": _name_col("company", free, df["company"], help=usual_hint),
        "Party GSTIN": CC.TextColumn(help=usual_hint),
        "Branch": _name_col("branch", free, df["branch"], help=usual_hint)})
    if purchase:
        for label in PRE_BILL_COLS:
            cols[label] = [None] * n
            config[label] = CC.NumberColumn(min_value=0.0, format="%.2f")
    grid = _grid(key, pd.DataFrame(cols), config,
                 "One row per item. Several rows with the same party, bill no. and date are saved as one bill. "
                 "Details left empty are filled in from the contract and from the party's last bill, as in the form."
                 + (" Pre-bill expenses (Adhat … Discount) are per item." if purchase else ""))

    parties, products = Names(df["party"], open_orders.get("party")), Names(df["commodity"])
    brokers, warehouses = Names(df["broker"]), Names(df["warehouse"])
    companies, types, subs = Names(df["company"]), Names(df["type"], ["Local", "Import"]), Names(df["sub_type"])
    usual = _party_defaults(df)
    first_company = (choices.options(None, df["company"]) or [None])[0]
    groups: dict[tuple, dict] = {}
    for i, r in grid.iterrows():
        if all(_blank(r[c]) for c in ("Party", "Product", "Weight (kg)", "Rate (₹/kg)", "Against contract")):
            continue
        order = orders.get(r["Against contract"]) if not _blank(r["Against contract"]) else None
        party = parties(r["Party"]) or (parties(order["party"]) if order is not None else "")
        prev = usual(party)
        product = products(r["Product"]) or (products(order["commodity"]) if order is not None else "")
        rate = _num(r["Rate (₹/kg)"]) or (float(order["rate"]) if order is not None else 0.0)
        qty = _num(r["Weight (kg)"]) or (float(order["bal_qty_mt"]) * 1000 if order is not None else 0.0)
        typ = types(r["Type"]) or _txt(prev.get("type")) or "Local"
        gst = (0.0 if typ == "Import" else 5.0) if _blank(r["GST %"]) else _num(r["GST %"])
        hsn = df[df["commodity"].astype(str).str.lower() == str(product).lower()]["hsn"].dropna()
        line = {"commodity": product, "qty": qty, "rate": rate, "gst_pct": gst,
                "order_row": int(order["source_row"]) if order is not None else None,
                "hsn": hsn.iloc[-1] if len(hsn) else None}
        if purchase:
            for label, fld in PRE_BILL_COLS.items():
                if _num(r[label]):
                    line[fld] = _num(r[label])
        elif not _blank(r.get("Linked purchase bill")):
            line["link_row"] = int(links[r["Linked purchase bill"]]["source_row"])
        gkey = (Names.key(party), _txt(r["Bill No"]) or f"auto-{Names.key(party)}-{r['Bill Date']}", str(r["Bill Date"]))
        header = {"party": party, "bill_no": _txt(r["Bill No"]), "bill_date": _day(r["Bill Date"]),
                  "stock_date": _day(r[stock_col]) or _day(r["Bill Date"]), "truck_no": _txt(r["Truck No"]),
                  "type": typ, "sub_type": subs(r["Sub Type"]) or _txt(prev.get("sub_type")),
                  "broker": brokers(r["Broker"]) or _txt(prev.get("broker")),
                  "warehouse": warehouses(r["Warehouse"]) or _txt(prev.get("warehouse")),
                  "company": companies(r["Company"]) or _txt(prev.get("company")) or first_company,
                  "gstin": _txt(r["Party GSTIN"]) or _txt(prev.get("gstin")),
                  "branch": _txt(r["Branch"]) or _txt(prev.get("branch"))}
        g = groups.setdefault(gkey, {"rows": [], "lines": [], "header": {k: v for k, v in header.items() if v}})
        g["rows"].append(i + 1)
        g["lines"].append(line)
    if not purchase:   # number our own invoices that were left empty
        used = list(df["bill_no"].dropna())
        for g in groups.values():
            if not g["header"].get("bill_no"):
                g["header"]["bill_no"] = str(next_number(used, "1"))
                used.append(g["header"]["bill_no"])

    if groups:
        prev_rows = [{"Rows": ", ".join(map(str, g["rows"])), "Party": g["header"].get("party", ""),
                      "Bill No": g["header"].get("bill_no", ""), "Items": len(g["lines"]),
                      "Type": g["header"].get("type", ""), "Broker": g["header"].get("broker", ""),
                      "Company": g["header"].get("company", ""), "Weight (kg)": sum(l["qty"] for l in g["lines"]),
                      "Amount": sum(l["qty"] * l["rate"] for l in g["lines"])} for g in groups.values()]
        st.markdown("**Bills to be saved** (with the contract's and the party's usual details filled in)")
        show_table(pd.DataFrame(prev_rows), money=["Weight (kg)", "Amount"])
    work = [(f"Row(s) {', '.join(map(str, g['rows']))}",
             lambda g=g: master.add_invoice_lines(kind, g["header"], g["lines"])) for g in groups.values()]
    _save_rows(key, master, work, f"{kind.lower()} bill(s)",
               [parties, products, brokers, warehouses, companies, types, subs])


# --------------------------------------------------------------------------- ③ / ⑧ notes
def _notes(kind: str, data, master: MasterFile):
    name = "Debit Note" if kind == "Purchase" else "Credit Note"
    key = f"tbl_note_{kind}"
    bills = _bill_labels(data.purchase if kind == "Purchase" else data.sales)
    st.subheader(f"{name}s - table")
    choices.add_new_box(key, {"reason": (NOTE_REASONS,), "expense": (NOTE_EXPENSES,)})
    reasons = NOTE_REASONS + [x for x in choices.added("reason") if x.lower() not in {b.lower() for b in NOTE_REASONS}]
    expenses = NOTE_EXPENSES + [x for x in choices.added("expense")
                                if x.lower() not in {b.lower() for b in NOTE_EXPENSES}]
    types = reasons + [EXPENSE_PREFIX + e for e in expenses]
    n = EMPTY_ROWS
    grid = _grid(key, pd.DataFrame({
        "Note No": [""] * n, "Date": [date.today()] * n, "Bill": [None] * n, "Reason / expense": [NOTE_REASONS[0]] * n,
        "Qty (kg)": [None] * n, "Rate (₹/kg)": [None] * n, "Amount excl. GST (₹)": [None] * n, "GST %": [None] * n}), {
        "Note No": CC.TextColumn(help="Rows with the same note no. (or, when empty, the same bill and date) "
                                      "make one note"),
        "Date": CC.DateColumn(format="DD-MM-YYYY", required=True),
        "Bill": CC.SelectboxColumn(options=list(bills), width="large", required=True),
        "Reason / expense": CC.SelectboxColumn(options=types, required=True, width="medium"),
        "Qty (kg)": CC.NumberColumn(min_value=0.0, format="%.2f"),
        "Rate (₹/kg)": CC.NumberColumn(min_value=0.0, format="%.2f", help="Empty = the bill's rate"),
        "Amount excl. GST (₹)": CC.NumberColumn(min_value=0.0, format="%.2f", help="Empty = qty × rate"),
        "GST %": CC.NumberColumn(min_value=0.0, max_value=28.0, format="%.1f", help="Empty = the bill's GST %")},
        "One row per reason or expense. Several rows on the same bill with the same note no. (or date) form one "
        "note - so one note can have several reasons and several expenses. Expenses carry no GST.")
    notes: dict[tuple, dict] = {}
    for i, r in grid.iterrows():
        if _blank(r["Bill"]):
            continue
        bill = bills[r["Bill"]]
        what = r["Reason / expense"] or NOTE_REASONS[0]
        gkey = (int(bill["source_row"]), _txt(r["Note No"]) or f"auto-{r['Date']}")
        g = notes.setdefault(gkey, {"rows": [], "row": int(bill["source_row"]), "party": bill["party"],
                                    "bill_no": _txt(bill["bill_no"]), "bill_qty": _num(bill["qty"]), "note": {
            "note_no": _txt(r["Note No"]) or None, "date": _day(r["Date"]), "lines": [], "expenses": []}})
        g["rows"].append(i + 1)
        if what.startswith(EXPENSE_PREFIX):
            g["note"]["expenses"].append({"type": what[len(EXPENSE_PREFIX):],
                                          "amount": _num(r["Amount excl. GST (₹)"])})
        else:
            base = bill["net_amount"] if kind == "Purchase" else bill["amount"]
            bill_gst = round(float(bill["gst"]) / float(base) * 200) / 2 if pd.notna(bill["gst"]) and base else 0.0
            qty = _num(r["Qty (kg)"])
            rate = _num(r["Rate (₹/kg)"]) or (float(bill["rate"]) if pd.notna(bill["rate"]) and qty else 0.0)
            g["note"]["lines"].append({"reason": what, "qty": qty, "rate": rate,
                                       "taxable": _num(r["Amount excl. GST (₹)"]) or round(qty * rate, 2),
                                       "gst_pct": bill_gst if _blank(r["GST %"]) else _num(r["GST %"])})
    if notes:
        prev = []
        for g in notes.values():
            t = sum(l["taxable"] * (1 + l["gst_pct"] / 100) for l in g["note"]["lines"]) + \
                sum(e["amount"] for e in g["note"]["expenses"])
            prev.append({"Rows": ", ".join(map(str, g["rows"])), "Party": g["party"],
                         "Note No": g["note"]["note_no"] or "(automatic)", "Reasons": len(g["note"]["lines"]),
                         "Expenses": len(g["note"]["expenses"]), "Total ₹": t})
        st.markdown("**Notes to be saved**")
        show_table(pd.DataFrame(prev), money=["Total ₹"])
    problems = []
    for g in notes.values():   # the same check as the form: a note can't take back more than the bill had
        q = sum(l["qty"] for l in g["note"]["lines"])
        if q > g["bill_qty"] + 0.001:
            problems.append(f"Row(s) {', '.join(map(str, g['rows']))}: quantity {q:,.2f} kg is more than the "
                            f"{g['bill_qty']:,.2f} kg on bill {g['bill_no'] or '-'} ({g['party']}).")
    work = [(f"Row(s) {', '.join(map(str, g['rows']))}",
             lambda g=g: master.add_note_detailed(kind, g["row"], g["note"])) for g in notes.values()]
    _save_rows(key, master, work, f"{name.lower()}(s)", problems=problems)


# --------------------------------------------------------------------------- ④ expenses
def _expenses(data, master: MasterFile):
    st.subheader("Expenses - table")
    c = st.columns([1, 2])
    kind = c[0].radio("Bill type", ["Purchase", "Sales"], horizontal=True, key="tbl_exp_kind",
                      format_func=lambda k: f"{k} bills")
    df = data.purchase if kind == "Purchase" else data.sales
    parties = sorted(df["party"].dropna().unique(), key=str.lower)
    pick = c[1].multiselect("Parties", parties, key=f"tbl_exp_party_{kind}", placeholder="All parties")
    rows = df[df["party"].isin(pick)] if pick else df
    fields = [f for group in EXPENSE_FIELDS[kind].values() for f in group]
    key = f"tbl_exp_{kind}_{'|'.join(pick)}"
    base = pd.DataFrame({"Row": rows["source_row"].astype(int), "Party": rows["party"],
                         "Bill No": rows["bill_no"].map(_txt), "Bill Date": rows["bill_date"],
                         "Product": rows["commodity"],
                         **{FIELD_LABELS[f]: rows[f].astype(float) for f in fields}}).reset_index(drop=True)
    if kind == "Purchase":
        st.caption("Pre-bill expenses and discount are entered with the purchase invoice.")
    st.caption("Change the amounts in the white columns and click Save - only the cells you change are written.")
    grid = st.data_editor(base, hide_index=True, width="stretch", key=f"{key}_{_nonce(key)}",
                          disabled=["Row", "Party", "Bill No", "Bill Date", "Product"], height=420,
                          column_config={"Row": CC.NumberColumn("Sheet row", format="%d"),
                                         "Bill Date": CC.DateColumn(format="DD-MM-YYYY"),
                                         **{FIELD_LABELS[f]: CC.NumberColumn(min_value=0.0, format="%.2f")
                                            for f in fields}})
    work = []
    for i, r in grid.iterrows():
        changes = {}
        for f in fields:
            old, new = base.loc[i, FIELD_LABELS[f]], r[FIELD_LABELS[f]]
            if (_blank(old) and _num(new)) or (not _blank(old) and abs(_num(new) - _num(old)) > 0.005):
                changes[f] = _num(new)
        if changes:
            work.append((f"Bill {r['Bill No']} (row {r['Row']})",
                         lambda row=int(r["Row"]), ch=changes: master.set_expenses(kind, row, ch)))
    _save_rows(key, master, work, "bill(s) with changed expenses")


# --------------------------------------------------------------------------- ⑤ / ⑨ payments & receipts
def _settlements(kind: str, master: MasterFile, ledger: R.Ledger):
    name = "Payment" if kind == "Purchase" else "Receipt"
    key = f"tbl_settle_{kind}"
    st.subheader(f"{name}s - table")
    bills = ledger.bills[ledger.bills["source_row"].notna()].sort_values(["party", "bill_date"])
    labels = {f"{r.party} · Bill {_txt(r.bill_no) or '-'} · due ₹{inr(r.outstanding)} · row {int(r.source_row)}": r
              for r in bills.itertuples()}
    n = EMPTY_ROWS
    grid = _grid(key, pd.DataFrame({"Date": [date.today()] * n, "Invoice": [None] * n,
                                    "Amount (₹)": [None] * n, "TDS (₹)": [None] * n, "Advance": [False] * n}), {
        "Advance": CC.CheckboxColumn("Keep extra as advance",
                                     help="Tick to allow more than the invoice's outstanding; the extra stays on "
                                          "this invoice as an advance (on account), as in the form"),
        "Date": CC.DateColumn(format="DD-MM-YYYY", required=True),
        "Invoice": CC.SelectboxColumn(options=list(labels), width="large", required=True),
        "Amount (₹)": CC.NumberColumn(min_value=0.0, format="%.2f", help="Empty = clear the invoice in full"),
        "TDS (₹)": CC.NumberColumn(min_value=0.0, format="%.2f")},
        f"One row per invoice the {name.lower()} is adjusted against - one {name.lower()} can be spread over "
        "several invoices by using several rows with the same date. Only parties with an unpaid bill are listed; "
        "a new party first needs a bill (" + ("② Purchase Invoice" if kind == "Purchase" else "⑦ Sales Invoice")
        + ").")
    groups: dict[tuple, dict] = {}
    problems = []
    for i, r in grid.iterrows():
        if _blank(r["Invoice"]):
            continue
        b = labels[r["Invoice"]]
        tds = _num(r["TDS (₹)"])
        amt = _num(r["Amount (₹)"]) or max(b.outstanding - tds, 0.0)
        g = groups.setdefault((b.party, str(r["Date"])), {"rows": [], "date": _day(r["Date"]), "alloc": [],
                                                          "out": {}, "party": b.party})
        g["rows"].append(i + 1)
        if amt + tds > b.outstanding + 1 and not bool(r["Advance"]):
            problems.append(f"Row {i + 1}: ₹ {inr(amt + tds, 2)} is more than the ₹ {inr(b.outstanding, 2)} "
                            f"outstanding on bill {_txt(b.bill_no) or '-'} ({b.party}). Type a smaller amount, or "
                            "tick *Keep extra as advance*.")
        g["alloc"].append((int(b.source_row), round(amt, 2), tds))
        g["out"][int(b.source_row)] = float(b.outstanding)
    if groups:
        st.markdown(f"**{name}s to be saved**")
        show_table(pd.DataFrame([{"Rows": ", ".join(map(str, g["rows"])), "Party": g["party"],
                                  "Invoices": len(g["alloc"]), "Amount": sum(a for _, a, _ in g["alloc"]),
                                  "TDS": sum(t for _, _, t in g["alloc"])} for g in groups.values()]),
                   money=["Amount", "TDS"])
    work = [(f"Row(s) {', '.join(map(str, g['rows']))}",
             lambda g=g: master.add_settlement(kind, g["date"], g["alloc"], g["out"])) for g in groups.values()]
    _save_rows(key, master, work, f"{name.lower()}(s)", problems=problems)
