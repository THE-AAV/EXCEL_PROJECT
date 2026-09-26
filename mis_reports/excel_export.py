"""Write all reports into one formatted Excel workbook.

Derived figures (net amounts, rates, closing balances, totals) are written as
Excel formulas so the workbook stays consistent if someone edits a number.
"""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
from xlsxwriter.utility import xl_col_to_name, xl_rowcol_to_cell

from .reports import BUCKET_NAMES, Filters, Ledger

FONT = "Arial"
NAVY = "#1F3864"
OVER90_COL = 8 + BUCKET_NAMES.index("Over 90 days")  # column of the ledger sheets


class _Styles:
    def __init__(self, wb):
        base = {"font_name": FONT, "font_size": 10}
        self.title = wb.add_format({**base, "bold": True, "font_size": 14, "font_color": NAVY})
        self.sub = wb.add_format({**base, "italic": True, "font_color": "#595959"})
        self.head = wb.add_format({**base, "bold": True, "font_color": "white", "bg_color": NAVY,
                                   "border": 1, "text_wrap": True, "valign": "vcenter", "align": "center"})
        self.section = wb.add_format({**base, "bold": True, "bg_color": "#D9E1F2", "border": 1})
        self.text = wb.add_format({**base, "border": 1})
        self.bold_text = wb.add_format({**base, "border": 1, "bold": True})
        self.money = wb.add_format({**base, "border": 1, "num_format": "#,##0;(#,##0);-"})
        self.money_bold = wb.add_format({**base, "border": 1, "bold": True, "bg_color": "#F2F2F2",
                                         "num_format": "#,##0;(#,##0);-"})
        self.rate = wb.add_format({**base, "border": 1, "num_format": "#,##0.00;(#,##0.00);-"})
        self.rate_bold = wb.add_format({**base, "border": 1, "bold": True, "bg_color": "#F2F2F2",
                                        "num_format": "#,##0.00;(#,##0.00);-"})
        self.pct = wb.add_format({**base, "border": 1, "num_format": "0.0%;(0.0%);-"})
        self.pct_bold = wb.add_format({**base, "border": 1, "bold": True, "bg_color": "#F2F2F2",
                                       "num_format": "0.0%;(0.0%);-"})
        self.date = wb.add_format({**base, "border": 1, "num_format": "dd-mmm-yyyy"})
        self.total_label = wb.add_format({**base, "border": 1, "bold": True, "bg_color": "#F2F2F2"})
        self.note = wb.add_format({**base, "font_color": "#595959", "text_wrap": True, "valign": "top"})
        self.red = wb.add_format({"font_color": "#C00000"})
        self.green = wb.add_format({"font_color": "#006100"})
        self.kpi_label = wb.add_format({**base, "bold": True, "border": 1, "bg_color": "#D9E1F2"})
        self.kpi_value = wb.add_format({**base, "bold": True, "border": 1, "font_size": 12,
                                        "num_format": "#,##0;(#,##0);-"})


def _filters_text(f: Filters) -> str:
    parts = []
    if f.date_from or f.date_to:
        parts.append(f"P&L period: {f.date_from or 'start'} to {f.date_to or 'latest'}")
    parts.append(f"Balances as on: {f.as_of or datetime.now().date()}")
    for label, vals in (("Type", f.types), ("Sub Type", f.sub_types), ("Company", f.companies),
                        ("Products", f.products)):
        if vals:
            parts.append(f"{label}: {', '.join(map(str, vals))}")
    return " | ".join(parts)


def _clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    return v


# --------------------------------------------------------------------------- P&L (vertical statement)
PNL_LINES = [
    # (label, key or formula template, style, total_mode) ; {c} = this column letter, {rX} = row of key X
    ("PURCHASE", None, "section", None),
    ("Purchase Qty (kg)", "purchase_qty", "money", "sum"),
    ("Purchase Value (excl. GST)", "purchase_value", "money", "sum"),
    ("Add: Pre-bill Expenses", "pre_bill_exp", "money", "sum"),
    ("Less: Purchase Discount", "purchase_discount", "money", "sum"),
    ("Net Purchase Cost", "={c}{purchase_value}+{c}{pre_bill_exp}-{c}{purchase_discount}", "money_bold", "sum"),
    ("Avg Landed Cost per kg", "=IF({c}{purchase_qty}>0,{c}{net_purchase}/{c}{purchase_qty},0)", "rate", "ratio"),
    ("SALES", None, "section", None),
    ("Sales Qty (kg)", "sales_qty", "money", "sum"),
    ("Sales Value (excl. GST)", "sales_value", "money", "sum"),
    ("Less: Sales Discount", "sales_discount", "money", "sum"),
    ("Net Sales", "={c}{sales_value}-{c}{sales_discount}", "money_bold", "sum"),
    ("Avg Sale Rate per kg", "=IF({c}{sales_qty}>0,{c}{net_sales}/{c}{sales_qty},0)", "rate", "ratio"),
    ("STOCK", None, "section", None),
    ("Closing Stock Qty (kg)", "={c}{purchase_qty}-{c}{sales_qty}", "money", "sum"),
    ("Closing Stock Value (at avg cost)", "={c}{closing_qty}*{c}{avg_cost_rate}", "money", "sum"),
    ("PROFIT & LOSS", None, "section", None),
    ("Cost of Goods Sold", "={c}{net_purchase}-{c}{closing_value}", "money", "sum"),
    ("Gross Profit", "={c}{net_sales}-{c}{cogs}", "money_bold", "sum"),
    ("Less: Post-bill Exp. (Purchase)", "post_exp_purchase", "money", "sum"),
    ("Less: Post-bill Exp. (Sales)", "post_exp_sales", "money", "sum"),
    ("Net Profit / (Loss)", "={c}{gross_profit}-{c}{post_exp_purchase}-{c}{post_exp_sales}", "money_bold", "sum"),
    ("Net Margin %", "=IF({c}{net_sales}<>0,{c}{net_profit}/{c}{net_sales},0)", "pct", "ratio"),
    ("Remark", "remark", "note", None),
]
_PNL_KEYS = ["", "purchase_qty", "purchase_value", "pre_bill_exp", "purchase_discount", "net_purchase",
             "avg_cost_rate", "", "sales_qty", "sales_value", "sales_discount", "net_sales", "avg_sales_rate",
             "", "closing_qty", "closing_value", "", "cogs", "gross_profit", "post_exp_purchase",
             "post_exp_sales", "net_profit", "margin_pct", "remark"]
_RATIO_TOTALS = {"avg_cost_rate": ("net_purchase", "purchase_qty"),
                 "avg_sales_rate": ("net_sales", "sales_qty"),
                 "margin_pct": ("net_profit", "net_sales")}


def _write_pnl(wb, st: _Styles, pnl: pd.DataFrame, f: Filters) -> dict:
    ws = wb.add_worksheet("Product P&L")
    ws.write(0, 0, "Product-wise Profit & Loss (exclusive of GST)", st.title)
    ws.write(1, 0, _filters_text(f), st.sub)
    top = 3
    ws.write(top, 0, "Particulars", st.head)
    products = pnl["product"].tolist() if len(pnl) else []
    for j, prod in enumerate(products):
        ws.write(top, 1 + j, prod, st.head)
    tcol = 1 + len(products)
    ws.write(top, tcol, "TOTAL", st.head)

    rows = {k: top + 2 + i for i, k in enumerate(_PNL_KEYS) if k}  # 1-based Excel rows
    for i, (label, spec, style, total_mode) in enumerate(PNL_LINES):
        r = top + 1 + i
        key = _PNL_KEYS[i]
        if spec is None:
            ws.write(r, 0, label, st.section)
            for j in range(len(products) + 1):
                ws.write_blank(r, 1 + j, None, st.section)
            continue
        ws.write(r, 0, label, st.bold_text if style.endswith("bold") else st.text)
        fmt = getattr(st, style)
        for j in range(len(products)):
            c = xl_col_to_name(1 + j)
            if spec.startswith("="):
                ws.write_formula(r, 1 + j, spec.format(c=c, **rows), fmt,
                                 _clean(pnl.iloc[j][key]))
            elif key == "remark":
                ws.write(r, 1 + j, pnl.iloc[j][key] or "", st.note)
            else:
                ws.write_number(r, 1 + j, float(pnl.iloc[j][key] or 0), fmt)
        tc = xl_col_to_name(tcol)
        bold = {"money": st.money_bold, "money_bold": st.money_bold, "rate": st.rate_bold, "pct": st.pct_bold}
        if total_mode == "sum" and products:
            ws.write_formula(r, tcol, f"=SUM(B{r + 1}:{xl_col_to_name(tcol - 1)}{r + 1})",
                             bold[style], float(pnl[key].sum()))
        elif total_mode == "ratio":
            num, den = _RATIO_TOTALS[key]
            cmp_ = ">0" if key != "margin_pct" else "<>0"
            nsum, dsum = pnl[num].sum(), pnl[den].sum()
            ws.write_formula(r, tcol, f"=IF({tc}{rows[den]}{cmp_},{tc}{rows[num]}/{tc}{rows[den]},0)",
                             bold[style], float(nsum / dsum) if dsum else 0.0)
        else:
            ws.write_blank(r, tcol, None, st.text)

    np_row = rows["net_profit"] - 1
    last = xl_col_to_name(tcol)
    ws.conditional_format(f"B{np_row + 1}:{last}{np_row + 1}",
                          {"type": "cell", "criteria": "<", "value": 0, "format": st.red})
    ws.conditional_format(f"B{np_row + 1}:{last}{np_row + 1}",
                          {"type": "cell", "criteria": ">", "value": 0, "format": st.green})
    ws.set_column(0, 0, 34)
    ws.set_column(1, tcol, 16)
    ws.set_row(rows["remark"] - 1, 60)
    ws.freeze_panes(top + 1, 1)
    note_r = top + len(PNL_LINES) + 2
    ws.merge_range(note_r, 0, note_r + 3, min(tcol, 8),
                   "How this is calculated: all amounts are before GST. Net Purchase Cost = purchase value + "
                   "pre-bill expenses (Adhat, AMC, labour, transport, WH load, bags, other) - discount. "
                   "Unsold stock is valued at the average landed cost per kg and carried forward, so only the "
                   "cost of what was sold is charged. Post-bill expenses (storage, brokerage, sampling, "
                   "repacking, transport, sales loading) are charged in full. Quantities are in kg.", st.note)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)
    return {"sheet": "'Product P&L'", "col": xl_col_to_name(tcol), "rows": rows}


# --------------------------------------------------------------------------- ledgers
def _write_ledger(wb, st: _Styles, ledger: Ledger, name: str, title: str, cols: dict, f: Filters) -> dict:
    """cols: labels for billed / paid / note columns."""
    ws = wb.add_worksheet(name)
    ws.write(0, 0, title, st.title)
    ws.write(1, 0, _filters_text(f) + " | amounts include GST", st.sub)
    headers = ["Party Name", "Opening Bal.", "No. of Bills", cols["billed"], cols["paid"], "TDS", cols["note"],
               "Closing Bal.", *BUCKET_NAMES, "Oldest Bill (days)", "Last Bill Date", "Last Payment Date"]
    top = 3
    for j, h in enumerate(headers):
        ws.write(top, j, h, st.head)
    s = ledger.summary
    nb = len(BUCKET_NAMES)
    for i, r in enumerate(s.itertuples()):
        row = top + 1 + i
        x = row + 1
        ws.write(row, 0, r.party, st.text)
        ws.write_number(row, 1, float(r.opening), st.money)
        ws.write_number(row, 2, int(r.bills), st.money)
        ws.write_number(row, 3, float(r.billed), st.money)
        ws.write_number(row, 4, float(r.paid), st.money)
        ws.write_number(row, 5, float(r.tds), st.money)
        ws.write_number(row, 6, float(r.note), st.money)
        ws.write_formula(row, 7, f"=B{x}+D{x}-E{x}-F{x}-G{x}", st.money_bold, float(r.closing))
        for k, b in enumerate(BUCKET_NAMES):
            ws.write_number(row, 8 + k, float(s.iloc[i][b]), st.money)
        ws.write(row, 8 + nb, _clean(r.oldest_days), st.money)
        for col, v in ((9 + nb, r.last_bill), (10 + nb, r.last_payment)):
            v = _clean(v)
            ws.write_datetime(row, col, v, st.date) if v else ws.write_blank(row, col, None, st.date)
    tot = top + 1 + len(s)
    ws.write(tot, 0, "TOTAL", st.total_label)
    for j in range(1, 8 + nb):
        if j == 2:
            ws.write_formula(tot, j, f"=SUM(C{top + 2}:C{tot})", st.money_bold, int(s["bills"].sum()))
            continue
        col = xl_col_to_name(j)
        key = ["", "opening", "", "billed", "paid", "tds", "note", "closing", *BUCKET_NAMES][j]
        ws.write_formula(tot, j, f"=SUM({col}{top + 2}:{col}{tot})", st.money_bold, float(s[key].sum()))
    for j in range(8 + nb, 11 + nb):
        ws.write_blank(tot, j, None, st.total_label)
    if len(s):
        ws.conditional_format(top + 1, OVER90_COL, tot - 1, OVER90_COL,
                               {"type": "cell", "criteria": ">", "value": 0, "format": st.red})
        ws.conditional_format(top + 1, 7, tot - 1, 7,
                               {"type": "data_bar", "bar_color": "#9DC3E6", "bar_solid": True})
    ws.set_column(0, 0, 40)
    ws.set_column(1, 7 + nb, 15)
    ws.set_column(8 + nb, 10 + nb, 14)
    ws.freeze_panes(top + 1, 1)
    ws.autofilter(top, 0, max(tot - 1, top), len(headers) - 1)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)
    return {"sheet": f"'{name}'", "total_row": tot + 1}


def _write_bills(wb, st: _Styles, bills: pd.DataFrame, name: str, title: str):
    ws = wb.add_worksheet(name)
    ws.write(0, 0, title, st.title)
    ws.write(1, 0, "Payments are adjusted against the oldest bills first (FIFO).", st.sub)
    headers = ["Party Name", "Bill No.", "Bill Date", "Product", "Bill Amount", "Outstanding", "Days",
               "Age Bucket", "Master Sheet Row"]
    top = 3
    for j, h in enumerate(headers):
        ws.write(top, j, h, st.head)
    for i, r in enumerate(bills.itertuples()):
        row = top + 1 + i
        ws.write(row, 0, r.party, st.text)
        ws.write(row, 1, "" if pd.isna(r.bill_no) else str(r.bill_no), st.text)
        d = _clean(r.bill_date)
        ws.write_datetime(row, 2, d, st.date) if d else ws.write_blank(row, 2, None, st.date)
        ws.write(row, 3, r.product, st.text)
        ws.write_number(row, 4, float(r.bill_amount), st.money)
        ws.write_number(row, 5, float(r.outstanding), st.money)
        ws.write(row, 6, _clean(r.days), st.money)
        ws.write(row, 7, r.age_bucket, st.text)
        ws.write(row, 8, _clean(r.source_row), st.text)
    tot = top + 1 + len(bills)
    ws.write(tot, 0, "TOTAL", st.total_label)
    for j in (1, 2, 3, 6, 7, 8):
        ws.write_blank(tot, j, None, st.total_label)
    ws.write_formula(tot, 4, f"=SUM(E{top + 2}:E{tot})", st.money_bold, float(bills["bill_amount"].sum()))
    ws.write_formula(tot, 5, f"=SUM(F{top + 2}:F{tot})", st.money_bold, float(bills["outstanding"].sum()))
    if len(bills):
        ws.conditional_format(top + 1, 6, tot - 1, 6,
                               {"type": "cell", "criteria": ">", "value": 90, "format": st.red})
    ws.set_column(0, 0, 40)
    ws.set_column(1, 1, 22)
    ws.set_column(2, 8, 14)
    ws.freeze_panes(top + 1, 1)
    ws.autofilter(top, 0, max(tot - 1, top), len(headers) - 1)


def _write_simple(wb, st: _Styles, df: pd.DataFrame, name: str, title: str, headers: dict, money=(), rate=()):
    ws = wb.add_worksheet(name)
    ws.write(0, 0, title, st.title)
    top = 2
    keys = list(headers)
    for j, k in enumerate(keys):
        ws.write(top, j, headers[k], st.head)
    for i, r in enumerate(df.itertuples(index=False)):
        rec = r._asdict()
        for j, k in enumerate(keys):
            v = _clean(rec.get(k))
            fmt = st.money if k in money else st.rate if k in rate else st.text
            ws.write(top + 1 + i, j, "" if v is None else v, fmt)
    ws.set_column(0, len(keys) - 1, 18)
    ws.set_column(len(keys) - 1, len(keys) - 1, 70 if name == "Data Checks" else 18)
    if len(df):
        ws.autofilter(top, 0, top + len(df), len(keys) - 1)


def _write_summary(ws, st: _Styles, f: Filters, pnl_ref: dict, cred_ref: dict, debt_ref: dict, values: dict):
    ws.write(0, 0, "Business Summary Report", st.title)
    ws.write(1, 0, f"Generated on {datetime.now():%d-%b-%Y %H:%M} | {_filters_text(f)}", st.sub)
    p, pc, pr = pnl_ref["sheet"], pnl_ref["col"], pnl_ref["rows"]
    kpis = [
        ("PROFIT & LOSS (excl. GST)", None, None),
        ("Net Sales", f"={p}!{pc}{pr['net_sales']}", values["net_sales"]),
        ("Cost of Goods Sold", f"={p}!{pc}{pr['cogs']}", values["cogs"]),
        ("Gross Profit", f"={p}!{pc}{pr['gross_profit']}", values["gross_profit"]),
        ("Post-bill Expenses", f"={p}!{pc}{pr['post_exp_purchase']}+{p}!{pc}{pr['post_exp_sales']}",
         values["post_bill_exp"]),
        ("Net Profit / (Loss)", f"={p}!{pc}{pr['net_profit']}", values["net_profit"]),
        ("Closing Stock Value", f"={p}!{pc}{pr['closing_value']}", values["closing_value"]),
        ("PAYABLES - CREDITORS (incl. GST)", None, None),
        ("Total Payable (Closing)", f"={cred_ref['sheet']}!H{cred_ref['total_row']}", values["payable"]),
        ("Payable overdue > 90 days", f"={cred_ref['sheet']}!{xl_col_to_name(OVER90_COL)}{cred_ref['total_row']}", values["payable_90"]),
        ("RECEIVABLES - DEBTORS (incl. GST)", None, None),
        ("Total Receivable (Closing)", f"={debt_ref['sheet']}!H{debt_ref['total_row']}", values["receivable"]),
        ("Receivable overdue > 90 days", f"={debt_ref['sheet']}!{xl_col_to_name(OVER90_COL)}{debt_ref['total_row']}", values["receivable_90"]),
    ]
    for i, (label, formula, val) in enumerate(kpis):
        r = 3 + i
        if formula is None:
            ws.merge_range(r, 0, r, 1, label, st.section)
        else:
            ws.write(r, 0, label, st.kpi_label)
            ws.write_formula(r, 1, formula, st.kpi_value, float(val))
    ws.set_column(0, 0, 36)
    ws.set_column(1, 1, 22)
    r = 3 + len(kpis) + 1
    ws.merge_range(r, 0, r + 4, 3,
                   "Sheets in this file: Product P&L (product-wise profit, excl. GST) | Creditors & Creditor Bills "
                   "(what we owe suppliers, with ageing) | Debtors & Debtor Bills (what customers owe us, with ageing)"
                   " | Open Orders (pending PO/SO) | Data Checks (rows in the Master Sheet that need attention).",
                   st.note)


def build_workbook(pnl: pd.DataFrame, cred: Ledger, debt: Ledger, orders: pd.DataFrame,
                   checks: pd.DataFrame, f: Filters) -> bytes:
    import xlsxwriter

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "nan_inf_to_errors": True})
    st = _Styles(wb)
    summary_ws = wb.add_worksheet("Summary")
    pnl_ref = _write_pnl(wb, st, pnl, f)
    cred_ref = _write_ledger(wb, st, cred, "Creditors", "Creditors (Payables) - Purchase Parties",
                             {"billed": "Payable Amount", "paid": "Paid Amount", "note": "Debit Note / Other Ded."}, f)
    _write_bills(wb, st, cred.bills, "Creditor Bills", "Outstanding Purchase Bills (Creditors)")
    debt_ref = _write_ledger(wb, st, debt, "Debtors", "Debtors (Receivables) - Sales Parties",
                             {"billed": "Receivable Amount", "paid": "Received Amount",
                              "note": "Credit Note / Other Ded."}, f)
    _write_bills(wb, st, debt.bills, "Debtor Bills", "Outstanding Sales Bills (Debtors)")
    _write_simple(wb, st, orders, "Open Orders", "Pending Purchase / Sales Orders",
                  {"order_type": "Order Type", "product": "Product", "contracts": "Contracts",
                   "bal_qty_kg": "Balance Qty (kg)", "amount": "Amount", "avg_rate": "Avg Rate per kg"},
                  money={"contracts", "bal_qty_kg", "amount"}, rate={"avg_rate"})
    _write_simple(wb, st, checks, "Data Checks", "Rows in the Master Sheet that need attention",
                  {"sheet": "Sheet", "row": "Row No.", "party": "Party", "issue": "Issue"})

    def tot(df, col):
        return float(df[col].sum()) if len(df) and col in df else 0.0
    values = {k: tot(pnl, k) for k in ("net_sales", "cogs", "gross_profit", "post_bill_exp",
                                       "net_profit", "closing_value")}
    values.update(payable=tot(cred.summary, "closing"), payable_90=tot(cred.summary, "Over 90 days"),
                  receivable=tot(debt.summary, "closing"), receivable_90=tot(debt.summary, "Over 90 days"))
    _write_summary(summary_ws, st, f, pnl_ref, cred_ref, debt_ref, values)
    summary_ws.activate()
    wb.close()
    return buf.getvalue()
