"""Build the Master Sheet (Domestic) workbook from the business data.

The result has the same sheets, columns and formulas as the hand-made Master Sheet: Main Display, Display,
Purchase, PO, SO, Sales, Total Debtor Creditor and masters (plus Debit Notes / Credit Notes when there are any).

Formula columns (Amount, Total Pre Bill Exp, Net Amount, Bill Amt, Final Amt, Brokerage, Bal Qty ...) get the
sheet's formula when the stored figure is what that formula gives, and the stored figure otherwise, so nothing
typed over a formula is lost. Every formula cell also carries its calculated value, so the file reads correctly
before anyone opens it in Excel; Excel recalculates everything when it is opened.
"""
from __future__ import annotations

import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .loader import DATE_FIELDS, NOTE_COLUMNS, NOTE_SHEETS, TEXT_FIELDS, MasterData, _norm, party_key
from .xlsx_edit import Book, _round_half_up

NUM = '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)'
DATE = "mm-dd-yy"  # Excel's built-in short date: shown in the computer's own date order


@dataclass
class Col:
    header: str
    field: str | None = None                 # stored field (loader name); None for extra / formula-only columns
    formula: str | None = None               # with {r} for this row
    calc: Callable | None = None             # the formula in Python: calc(row getter) -> value
    date: bool = False
    num: bool = False
    alt: tuple | None = None                 # another (formula, calc) the sheet uses for the same column


def F(header, field, **kw):
    return Col(header, field, date=field in DATE_FIELDS, **kw)


def X(header, date=False, num=False):
    """A column the reports don't use; kept as imported."""
    return Col(header, None, date=date, num=num)


def FX(header, formula, calc=None, field=None, num=True, alt=None):
    return Col(header, field, formula=formula, calc=calc, num=num, alt=alt)


def _n(v) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and not math.isnan(v) else 0.0


PURCHASE = [
    FX("SR.NO.", None, num=False), FX("PSN", "=VLOOKUP(H{r},masters!B:C,2,0)", num=False),
    F("Com.", "company"), F("Type", "type"), F("Sub Type", "sub_type"), F("Warehouse", "warehouse"),
    F("Broker", "broker"), F("PARTY NAME", "party"), F("PARTY GSTN NO", "gstin"), F("BRANCH", "branch"),
    F("BILL NO.", "bill_no"), F("BILL DATE", "bill_date"), F("WH In Date", "stock_date"), F("TRUCK NO", "truck_no"),
    X("BL NO"), X("BL Date", date=True), X("BE No"), X("BE Date", date=True),
    F("COMMODITY", "commodity"), F("HSN CODE", "hsn"), F("NO OF BAG", "no_of_bags"),
    F("BILL WEIGHT", "bill_weight", num=True), F("WEIGHT", "qty", num=True), X("Bag Wt Diff.", num=True),
    F("RATE", "rate", num=True), X("Amt in USD", num=True), X("Exg Rate", num=True),
    FX("Amount befor GST", "=W{r}*Y{r}", lambda g: _n(g("W")) * _n(g("Y")), "amount"),
    F("Adhat", "adhat", num=True), F("AMC", "amc", num=True), F("Labour", "labour", num=True),
    F("Transporation", "transport_pre", num=True), F("WH Load", "wh_load", num=True), F("Bags", "bags", num=True),
    F("Other", "other_pre", num=True),
    FX("Total Pre Bill Exp", "=SUM(AC{r}:AI{r})", lambda g: sum(_n(g(c)) for c in ("AC", "AD", "AE", "AF", "AG", "AH", "AI")),
       "pre_exp"),
    F("Discount", "discount", num=True),
    FX("Net Amount befor GST", "=AB{r}+AJ{r}-AK{r}", lambda g: _n(g("AB")) + _n(g("AJ")) - _n(g("AK")), "net_amount"),
    F("GST", "gst", num=True),
    FX("Bill Amt", "=AB{r}+AM{r}", lambda g: _n(g("AB")) + _n(g("AM")), "bill_amt"),
    F("Vatav", "vatav", num=True),
    FX("Final Amt.", "=AN{r}-AO{r}", lambda g: _n(g("AN")) - _n(g("AO")), "final_amt"),
    F("S Inv", "sales_inv"), X("Pur Status"), F("Status", "status"),
    FX("Due Days", '=IF(AS{r}="Paid","Closed",($AT$1+1)-M{r})', num=False),
    F("Date", "pay_date"), F("Amount", "paid", num=True), F("TDS", "tds", num=True),
    F("Debit Note / Other de.", "note", num=True),
    FX("Total Post exp.", "=BA{r}+SUM(BC{r}:BF{r})",
       lambda g: _n(g("BA")) + sum(_n(g(c)) for c in ("BC", "BD", "BE", "BF")), "post_exp"),
    FX("Storage Days", "=IF(BB{r}>0,(BB{r}+1)-M{r},($AT$1+1)-M{r})", num=False),
    F("Storage Amt.", "storage", num=True), X("Storage Out Date", date=True),
    FX("Brokerage", "=ROUND(AB{r}*0.1%,0)", lambda g: _round_half_up(_n(g("AB")) * 0.001, 0), "brokerage"),
    F("Sampling Expenses", "sampling", num=True), F("Repacking charges", "repacking", num=True),
    F("Transportation", "transport_post", num=True),
]
PURCHASE_TOP = {1: {"AC": "Pre Bill Expenses", "AS": "Payment Details", "AT": "=TODAY()", "AY": "Post Bill Expenses"},
                2: {**{c: "(+)" for c in ("AC", "AD", "AE", "AF", "AG", "AH", "AI")}, "AK": "(-)"}}

SALES = [
    FX("SR.NO.", None, num=False), FX("PSN", "=VLOOKUP(H{r},masters!E:F,2,0)", num=False),
    F("Com", "company"), F("Type", "type"), F("Sub Type", "sub_type"), F("Warehouse", "warehouse"),
    F("Broker", "broker"), F("PARTY NAME", "party"), F("PARTY GSTN NO", "gstin"), F("BRANCH", "branch"),
    F("BILL NO.", "bill_no"), F("BILL DATE", "bill_date"), F("Delivery Date", "stock_date"), F("TRUCK NO", "truck_no"),
    F("COMMODITY", "commodity"), F("HSN CODE", "hsn"), F("NO OF BAG", "no_of_bags"),
    F("BILL WEIGHT", "bill_weight", num=True), F("WH Weight", "qty", num=True), X("Bag Wt Diff.", num=True),
    F("RATE", "rate", num=True), X("Amt in USD", num=True), X("Exg Rate", num=True),
    FX("Amount before GST", "=R{r}*U{r}", lambda g: _n(g("R")) * _n(g("U")), "amount",
       alt=("=S{r}*U{r}", lambda g: _n(g("S")) * _n(g("U")))),  # some rows use the WH weight
    F("Discount", "discount", num=True),
    FX("Net Amount befor GST", "=X{r}-Y{r}", lambda g: _n(g("X")) - _n(g("Y")), "net_amount"),
    F("GST", "gst", num=True),
    FX("Bill Amt", "=X{r}+AA{r}", lambda g: _n(g("X")) + _n(g("AA")), "bill_amt"),
    F("P Inv", "purchase_inv"), X("Sales Status"), F("Status", "status"),
    FX("Due Days", '=IF(AE{r}="Recd","Closed",($AF$1+1)-M{r})', num=False),
    F("Date", "pay_date"), F("Amount", "paid", num=True), F("TDS", "tds", num=True),
    F("Debit Note / Other de.", "note", num=True),
    FX("Total Post Exp.", "=SUM(AL{r}:AN{r})", lambda g: sum(_n(g(c)) for c in ("AL", "AM", "AN")), "post_exp"),
    FX("Brokerage", "=ROUND(Z{r}*0.1%,0)", lambda g: _round_half_up(_n(g("Z")) * 0.001, 0), "brokerage"),
    F("Loading / Unloading", "loading", num=True), F("Repacking", "repacking", num=True),
]
SALES_TOP = {1: {"AE": "Receipt Details", "AF": "=TODAY()", "AK": "Post Bill Expenses"}, 2: {"Y": "(-)"}}

ORDERS = [
    F("Contract No", "contract_no"), F("Date", "date"), X("Sales \nContract No"), F("Company \nName", "company"),
    F("Party Name", "party"), F("Branch", "branch"), F("Broker Name", "broker"), F("Quality", "commodity"),
    F("Qty\nMts", "qty_mt", num=True), F("Rate", "rate", num=True), F("Packing", "packing"),
    F("Delivery Date", "delivery_date"), F("Delivery Place", "delivery_place"), F("Cancel Qty", "cancel_qty", num=True),
    FX("Revised\nQty", "=I{r}-N{r}", lambda g: _n(g("I")) - _n(g("N")), "revised_qty"),
    F("Recd Qty", "recd_qty", num=True), F("Qty + / -", "qty_diff", num=True),
    FX("Bal Qty", "=O{r}-P{r}+Q{r}", lambda g: _n(g("O")) - _n(g("P")) + _n(g("Q")), "bal_qty_mt"),
    FX("AMT", "=(R{r}*1000)*J{r}", lambda g: _n(g("R")) * 1000 * _n(g("J")), "amount"),
    FX("Status", '=IF(R{r}=0,"Closed","Open")', lambda g: "Closed" if _n(g("R")) == 0 else "Open", "status", num=False),
    X("Cancel date", date=True), F("Recd Date", "recd_date"), F("Bill Date", "bill_date"), F("Bill No", "bill_no"),
    F("BILL RATE", "bill_rate", num=True), F("LORRY NO", "lorry_no"), X("Unloading Date", date=True),
    F("Bill Weight", "bill_weight", num=True), X("Loading Weight", num=True), X("Unloading Weight", num=True),
    X("Short / Ex. Weight", num=True), F("Warehouse", "warehouse"),
]

NOTES = [F(h, f, num=f in ("qty", "rate", "taxable", "gst_pct", "gst", "other", "total")) for f, h in NOTE_COLUMNS.items()]

HEAD_FILL = PatternFill("solid", fgColor="DDEBF7")
TOP_FILL = PatternFill("solid", fgColor="FFF2CC")
THIN = Side(style="thin", color="B4C6E7")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
BOLD = Font(bold=True)


class _Cache:
    """Calculated values for formula cells, written into the file after openpyxl has saved it."""

    def __init__(self):
        self.values: dict[str, dict[str, object]] = {}

    def put(self, sheet: str, ref: str, v):
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return
        self.values.setdefault(sheet, {})[ref] = v


def _cell_value(v):
    """Values as Excel should hold them: dates as dates, number-like codes stay text."""
    if v is None or v is pd.NaT or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        v = v.item()
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return int(v)
    return v


def _typed_text(v):
    """Text fields that were numbers in Excel (bill no. 917, contract no. 1) go back as numbers."""
    if isinstance(v, str) and re.fullmatch(r"-?(0|[1-9]\d{0,14})", v.strip()):
        return int(v.strip())
    return v


def _extra_value(v, is_date: bool):
    if is_date and isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(T[\d:]+)?", v):
        return datetime.fromisoformat(v)
    return v


def _close(a, b) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return str(a).strip().lower() == str(b).strip().lower()
    a, b = _n(a), _n(b)
    return abs(a - b) <= max(0.005, 1e-9 * max(abs(a), abs(b)))


def _unique(values) -> list[str]:
    """Like Excel's SORT(UNIQUE(...)): one entry per name, capitals ignored, sorted A-Z."""
    seen = {}
    for v in values:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        s = str(v).strip()
        if s and s.lower() not in seen:
            seen[s.lower()] = s
    return sorted(seen.values(), key=str.lower)


def _write_table(ws, cache: _Cache, cols: list[Col], df: pd.DataFrame, hdr: int, top: dict | None = None,
                 psn: dict | None = None) -> dict:
    """Writes the header on row `hdr` and one row per record below it. Returns {old source_row: new row}."""
    for r, cells in (top or {}).items():
        for col, v in cells.items():
            c = ws[f"{col}{r}"]
            c.value, c.font, c.fill, c.alignment = v, BOLD, TOP_FILL, Alignment(horizontal="center")
            if isinstance(v, str) and v.startswith("=TODAY"):
                c.number_format = DATE
    # columns in the data that this layout doesn't know go at the end, so nothing is lost
    known = {_norm(c.header) for c in cols}
    extra_headers = []
    for extra in (df["_extra"] if "_extra" in df else []):
        for h in (extra or {}):
            if _norm(h) not in known and _norm(h) not in {_norm(x) for x in extra_headers}:
                extra_headers.append(h)
    all_cols = cols + [X(h) for h in extra_headers]
    letters = [get_column_letter(i + 1) for i in range(len(all_cols))]
    for i, col in enumerate(all_cols):
        c = ws.cell(hdr, i + 1, col.header)
        c.font, c.fill, c.border = BOLD, HEAD_FILL, BOX
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[letters[i]].width = max(9, min(28, len(col.header.replace("\n", " ")) + 3))

    rows_map = {}
    records = df.to_dict(orient="records") if len(df) else []
    for n, rec in enumerate(records):
        r = hdr + 1 + n
        rows_map[rec.get("source_row")] = r
        extra = {_norm(k): v for k, v in (rec.get("_extra") or {}).items()}
        values: dict[str, object] = {}

        def get(letter):
            return values.get(letter)

        for i, col in enumerate(all_cols):
            L = letters[i]
            cell = ws[f"{L}{r}"]
            stored = _cell_value(rec.get(col.field)) if col.field else None
            if col.header == "SR.NO.":
                cell.value = 1 if n == 0 else f"=A{r - 1}+1"
                values[L] = n + 1
                if n:
                    cache.put(ws.title, f"{L}{r}", n + 1)
            elif col.header == "PSN" and psn is not None:
                cell.value = col.formula.format(r=r)
                values[L] = psn.get(str(rec.get("party") or "").strip().lower())
                cache.put(ws.title, f"{L}{r}", values[L] if values[L] is not None else "#N/A")
            elif col.formula and col.calc is None:        # Due Days / Storage Days: depend on today's date
                cell.value = col.formula.format(r=r)
            elif col.formula:
                calc = col.calc(get)
                if stored is None:                          # left empty in the sheet: stays empty
                    pass
                elif _close(stored, calc) or (col.alt and _close(stored, col.alt[1](get))):
                    cell.value = (col.formula if _close(stored, calc) else col.alt[0]).format(r=r)
                    values[L] = stored
                    cache.put(ws.title, f"{L}{r}", stored)
                else:
                    cell.value = values[L] = stored
            else:
                if col.field:
                    v = _typed_text(stored) if col.field in TEXT_FIELDS else stored
                else:
                    v = _extra_value(extra.get(_norm(col.header)), col.date)
                cell.value = values[L] = v
            if col.date:
                cell.number_format = DATE
            elif col.num:
                cell.number_format = NUM
    return rows_map


def _write_masters(ws, cache: _Cache, data: MasterData):
    """The lists sheet: parties (their PSN numbers), products, warehouses, types, sub types and brokers."""
    lists = {
        ("B", "C"): _unique(data.purchase["party"]), ("E", "F"): _unique(data.sales["party"]),
        ("I", "H"): _unique(data.purchase["commodity"]), ("L", "K"): _unique(data.purchase["warehouse"]),
        ("O", "N"): _unique(data.purchase["type"]), ("Q", "P"): _unique(data.sales["type"]),
        ("T", "S"): _unique(data.purchase["broker"]), ("V", "U"): _unique(data.sales["broker"]),
    }
    # sub types sit under the types, as in the hand-made sheet (from row 13, lower when there are many types)
    sub = max(13, 5 + max(len(lists[("O", "N")]), len(lists[("Q", "P")])))
    heads = {"B1": "Max", "C1": "=MAX(Purchase!B:B)", "E1": "Max", "F1": "=MAX(Sales!B:B)",
             "B2": "Purchase Parties", "E2": "Sales Parties", "O2": "Purchase", "Q2": "Sales",
             "T2": "Purchase", "V2": "Sales", "B3": "Party Name", "C3": "PSN", "E3": "Party Name",
             "F3": "PSN", "H3": "Sr. No.", "I3": "Product", "K3": "Sr. No.", "L3": "Warehouse",
             "N3": "Sr. No.", "O3": "Type", "P3": "Sr. No.", "Q3": "Type", "S3": "Sr. No.",
             "T3": "Broker Name", "U3": "Sr. No.", "V3": "Broker Name",
             f"O{sub}": "Purchase", f"Q{sub}": "Sales", f"N{sub + 1}": "Sr. No.", f"O{sub + 1}": "Sub Type",
             f"P{sub + 1}": "Sr. No.", f"Q{sub + 1}": "Sub Type"}
    for ref, v in heads.items():
        ws[ref] = v
        ws[ref].font = BOLD
        if v in ("Party Name", "PSN", "Sr. No.", "Product", "Warehouse", "Type", "Sub Type", "Broker Name"):
            ws[ref].fill = HEAD_FILL
    cache.put(ws.title, "C1", len(lists[("B", "C")]))
    cache.put(ws.title, "F1", len(lists[("E", "F")]))
    blocks = [(name_col, no_col, 4, names) for (name_col, no_col), names in lists.items()]
    blocks += [("O", "N", sub + 2, _unique(data.purchase["sub_type"])), ("Q", "P", sub + 2, _unique(data.sales["sub_type"]))]
    for name_col, no_col, first, names in blocks:
        ws.column_dimensions[name_col].width = 32 if name_col in "BE" else 20
        for i, name in enumerate(names):
            r = first + i
            ws[f"{name_col}{r}"] = name
            if i == 0:
                ws[f"{no_col}{r}"] = 1
            else:
                ws[f"{no_col}{r}"] = f'=IF({name_col}{r}>"",{no_col}{r - 1}+1,"")'
                cache.put(ws.title, f"{no_col}{r}", i + 1)
    return ({n.lower(): i + 1 for i, n in enumerate(lists[("B", "C")])},
            {n.lower(): i + 1 for i, n in enumerate(lists[("E", "F")])})


def _write_debtor_creditor(ws, cache: _Cache, data: MasterData, psn_p: dict, psn_s: dict):
    t = ws.title
    q = f"'{t}'"
    for ref, v in {"A1": "Max", "B1": "=MAX(Purchase!B:B)", "K1": "Max", "L1": "=MAX(Sales!B:B)",
                   "B2": "Purchase Parties", "L2": "Sales Parties"}.items():
        ws[ref] = v
        ws[ref].font = BOLD
    cache.put(t, "B1", len(psn_p))
    cache.put(t, "L1", len(psn_s))
    heads = ["PSN", "Party Name", "Opening Bal.", "Payable Amount", "Paid Amount", "TDS",
             "Debit Note / Oth Deduction", "Closing Bal.", "Remark", None, "PSN", "Party Name", "Opening Bal.",
             "Receivable Amount", "Recd Amount", "TDS", "Credit Note / Oth Deduction", "Closing Bal.", "Remark"]
    for i, h in enumerate(heads):
        if h:
            c = ws.cell(3, i + 1, h)
            c.font, c.fill, c.border = BOLD, HEAD_FILL, BOX
            c.alignment = Alignment(horizontal="center", wrap_text=True)
    for col, w in zip("ABCDEFGHIJKLMNOPQRS", (6, 34, 14, 16, 16, 12, 16, 16, 12, 3, 6, 34, 14, 16, 16, 12, 16, 16, 12)):
        ws.column_dimensions[col].width = w

    # side: (bills, psn map, opening, first col, sheet, amount col, paid col, tds col, note col, amount field)
    sides = [
        (data.purchase, psn_p, data.opening_creditors, 1, "Purchase", "AP", "AV", "AW", "AX", "final_amt"),
        (data.sales, psn_s, data.opening_debtors, 11, "Sales", "AB", "AH", "AI", "AJ", "bill_amt"),
    ]
    for bills, psn, opening, c0, sheet, amt_c, paid_c, tds_c, note_c, amt_f in sides:
        L = [get_column_letter(c0 + k) for k in range(8)]   # PSN, name, opening, amount, paid, tds, note, closing
        b = bills.assign(_psn=bills["party"].map(lambda p: psn.get(str(p or "").strip().lower())))
        first_name = b.dropna(subset=["_psn"]).groupby("_psn")["party"].first()
        sums = b.groupby("_psn")[[amt_f, "paid", "tds", "note"]].sum(min_count=1).fillna(0)
        by_key = {party_key(v): k for k, v in first_name.items()}
        rows = [(k, first_name[k]) for k in sorted(first_name.index)]
        rows += [(None, name) for key, (name, _) in opening.items() if key not in by_key]
        for n, (k, name) in enumerate(rows):
            r = 4 + n
            opening_bal = opening.get(party_key(name), ("", 0.0))[1]
            ws[f"{L[2]}{r}"] = opening_bal or 0
            if k is None:  # opening balance only, no bills yet
                ws[f"{L[1]}{r}"] = name
                ws[f"{L[7]}{r}"] = f"={L[2]}{r}"
                cache.put(t, f"{L[7]}{r}", opening_bal)
                continue
            s = sums.loc[k]
            ws[f"{L[0]}{r}"] = int(k) if n == 0 else f'=IF({L[0]}{r - 1}<${L[1]}$1,{L[0]}{r - 1}+1,"")'
            if n:
                cache.put(t, f"{L[0]}{r}", int(k))
            ws[f"{L[1]}{r}"] = f'=IFERROR(VLOOKUP({L[0]}{r},{sheet}!B:H,7,0),"")'
            cache.put(t, f"{L[1]}{r}", name)
            for col, src, v in ((L[3], amt_c, s[amt_f]), (L[4], paid_c, s["paid"]), (L[5], tds_c, s["tds"]),
                                (L[6], note_c, s["note"])):
                ws[f"{col}{r}"] = f"=SUMIF({sheet}!B:B,{q}!{L[0]}{r},{sheet}!{src}:{src})"
                cache.put(t, f"{col}{r}", float(v))
            ws[f"{L[7]}{r}"] = f"={L[2]}{r}+{L[3]}{r}-{L[4]}{r}-{L[5]}{r}-{L[6]}{r}"
            cache.put(t, f"{L[7]}{r}", opening_bal + s[amt_f] - s["paid"] - s["tds"] - s["note"])
            for col in L[2:]:
                ws[f"{col}{r}"].number_format = NUM
        # empty formula rows below, like the hand-made sheet, so parties added later in Excel show up too
        for r in range(4 + len(rows), 4 + max(len(rows) + 50, 106)):
            ws[f"{L[0]}{r}"] = f'=IF({L[0]}{r - 1}<${L[1]}$1,{L[0]}{r - 1}+1,"")'
            ws[f"{L[1]}{r}"] = f'=IFERROR(VLOOKUP({L[0]}{r},{sheet}!B:H,7,0),"")'
            ws[f"{L[2]}{r}"] = 0
            cache.put(t, f"{L[0]}{r}", "")
            cache.put(t, f"{L[1]}{r}", "")
            for col, src in ((L[3], amt_c), (L[4], paid_c), (L[5], tds_c), (L[6], note_c)):
                ws[f"{col}{r}"] = f"=SUMIF({sheet}!B:B,{q}!{L[0]}{r},{sheet}!{src}:{src})"
                cache.put(t, f"{col}{r}", 0)
            ws[f"{L[7]}{r}"] = f"={L[2]}{r}+{L[3]}{r}-{L[4]}{r}-{L[5]}{r}-{L[6]}{r}"
            cache.put(t, f"{L[7]}{r}", 0)
            for col in L[2:]:
                ws[f"{col}{r}"].number_format = NUM
    ws.freeze_panes = "A4"


DISPLAY = {
    "B1": "Product", "B2": "Type", "B3": "Sub Type",
    "C5": "Particulars", "D5": "Qty", "E5": "Amount", "F5": "Rate", "H5": "Particulars", "I5": "Qty", "J5": "Amount",
    "K5": "Rate", "N5": "Pre Bill Exp.", "O5": "Amt.", "P5": "Type", "R5": "Post Bill Exp.", "S5": "Amt.", "T5": "Type",
    "C6": "Purchase", "H6": "Sales", "C7": "=C1", "D7": "=SUMIFS(Purchase!W:W,Purchase!S:S,Display!C7)",
    "E7": "=SUMIFS(Purchase!AB:AB,Purchase!S:S,Display!C7)", "F7": "=E7/D7", "H7": "=C7",
    "I7": "=SUMIFS(Sales!S:S,Sales!O:O,Display!H7)", "J7": "=SUMIFS(Sales!X:X,Sales!O:O,Display!H7)", "K7": "=J7/I7",
    "B10": "Add", "C10": "Pre Bill Exp. Pur", "E10": "=SUMIFS(Purchase!AJ:AJ,Purchase!S:S,Display!C7)",
    "B11": "Less", "C11": "Discount", "E11": "=SUMIFS(Purchase!AK:AK,Purchase!S:S,Display!C7)", "G11": "Less",
    "H11": "Discount", "J11": "=SUMIFS(Sales!Y:Y,Sales!O:O,Display!C1)",
    "C13": "Total Pre Bill Exp.", "D13": "=D10-D11", "E13": "=E10-E11",
    "C15": "Total Purchase", "D15": "=D7+D13", "E15": "=E7+E13", "F15": "=E15/D15",
    "B17": "Add", "C17": "Post Bill Exp. Pur", "E17": "=SUMIFS(Purchase!AY:AY,Purchase!S:S,Display!C7)",
    "C18": "Post Bill Exp. Sales", "E18": "=SUMIFS(Sales!AK:AK,Sales!O:O,Display!C1)",
    "C20": "Total Post Bill Exp.", "D20": "=SUM(D17:D19)", "E20": "=SUM(E17:E19)",
    "C22": "Total COGS", "D22": "=D15+D20", "E22": "=E15+E20", "F22": "=E22/D22",
    "H22": "Total Sales", "I22": "=I7-I11", "J22": "=J7-J11", "K22": "=J22/I22",
    "C24": "Profit & Loss", "E24": "=J22-E22",
    "H26": "Closing Stock", "I26": "Qty", "J26": "Amount", "H27": "=C1", "I27": "=D22-I22", "K27": "=J27/I27",
    "N14": None, "O14": "=SUM(O6:O13)", "S14": "=SUM(S6:S13)",
    "N20": "Pending Purchase Order", "P20": "Open", "N21": "Product", "O21": "Bal. Qty", "P21": "Amt.", "Q21": "Avg Rate",
    "N22": "=C1", "O22": "=SUMIFS(PO!R:R,PO!H:H,Display!N22,PO!T:T,Display!P20)*1000",
    "P22": "=SUMIFS(PO!S:S,PO!H:H,Display!N22,PO!T:T,Display!P20)", "Q22": "=P22/O22",
}
PRE_EXP = [("Adhat", "AC"), ("AMC", "AD"), ("Labour", "AE"), ("Transporation", "AF"), ("WH Load", "AG"),
           ("Bags", "AH"), ("Other", "AI")]
POST_EXP = [("Storage Amt.", "BA"), ("Brokerage", "BC"), ("Sampling Expenses", "BD"), ("Repacking charges", "BE"),
            ("Transportation", "BF")]


def _write_display(ws, product: str):
    for ref, v in DISPLAY.items():
        if v is not None:
            ws[ref] = v
    ws["C1"] = product
    for i, (name, col) in enumerate(PRE_EXP):
        ws[f"N{6 + i}"], ws[f"O{6 + i}"], ws[f"P{6 + i}"] = (
            name, f"=SUMIFS(Purchase!{col}:{col},Purchase!S:S,Display!$C$1)", "Pur")
    for i, (name, col) in enumerate(POST_EXP):
        ws[f"R{6 + i}"], ws[f"S{6 + i}"], ws[f"T{6 + i}"] = (
            name, f"=SUMIFS(Purchase!{col}:{col},Purchase!S:S,Display!$C$1)", "Pur")
    ws["R12"], ws["S12"], ws["T12"] = "Brokerage", "=SUMIFS(Sales!AL:AL,Sales!O:O,Display!C1)", "Sales"
    ws["N16"], ws["O16"], ws["P16"] = "Discount", "=SUMIFS(Purchase!AK:AK,Purchase!S:S,Display!$C$1)", "Pur"
    ws["N17"], ws["O17"], ws["P17"] = "Discount", "=SUMIFS(Sales!Y:Y,Sales!O:O,Display!C1)", "Sales"
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str) and c.value.startswith("="):
                c.number_format = NUM
    for ref in ("B1", "C5", "D5", "E5", "F5", "H5", "I5", "J5", "K5", "N5", "O5", "P5", "R5", "S5", "T5", "C6", "H6",
                "C15", "C22", "H22", "C24", "H26", "N20", "N21", "O21", "P21", "Q21"):
        ws[ref].font = BOLD
    for col, w in (("B", 8), ("C", 22), ("H", 16), ("N", 22), ("R", 20)):
        ws.column_dimensions[col].width = w


def build_master_sheet(data: MasterData) -> bytes:
    """The Master Sheet workbook for `data`, as .xlsx bytes."""
    cache = _Cache()
    wb = Workbook()
    wb.remove(wb.active)
    main, display = wb.create_sheet("Main Display"), wb.create_sheet("Display")
    ws_p, ws_po, ws_so, ws_s = (wb.create_sheet(n) for n in ("Purchase", "PO", "SO", "Sales"))
    ws_tdc, ws_m = wb.create_sheet("Total Debtor Creditor"), wb.create_sheet("masters")

    psn_p, psn_s = _write_masters(ws_m, cache, data)
    pur_rows = _write_table(ws_p, cache, PURCHASE, data.purchase, 3, PURCHASE_TOP, psn_p)
    sal_rows = _write_table(ws_s, cache, SALES, data.sales, 3, SALES_TOP, psn_s)
    _write_table(ws_po, cache, ORDERS, data.po, 2)
    _write_table(ws_so, cache, ORDERS, data.so, 2)
    for ws, freeze in ((ws_p, "I4"), (ws_s, "I4"), (ws_po, "A3"), (ws_so, "A3")):
        ws.freeze_panes = freeze
    _write_debtor_creditor(ws_tdc, cache, data, psn_p, psn_s)

    top = data.purchase.assign(v=pd.to_numeric(data.purchase["amount"], errors="coerce")) \
        .groupby("commodity")["v"].sum().sort_values(ascending=False)
    _write_display(display, str(top.index[0]) if len(top) else "")
    main["A1"] = None

    for kind, rows in (("Purchase", pur_rows), ("Sales", sal_rows)):
        notes = data.debit_notes if kind == "Purchase" else data.credit_notes
        if notes is None or notes.empty:
            continue
        notes = notes.copy()
        # notes point at their bill by its row; bills are renumbered here, so the pointers follow
        notes["bill_row"] = notes["bill_row"].map(
            lambda v: rows.get(int(v)) if isinstance(v, (int, float)) and not math.isnan(v) else None)
        _write_table(wb.create_sheet(NOTE_SHEETS[kind]), cache, NOTES, notes, 1)

    return _with_cached_values(wb, cache)


def _with_cached_values(wb: Workbook, cache: _Cache) -> bytes:
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "master.xlsx")
    try:
        wb.save(path)
        book = Book(path)
        for sheet, values in cache.values.items():
            sh = book.sheet(sheet)
            for ref, v in values.items():
                if ref in sh.cells:
                    if isinstance(v, (datetime, date)):
                        continue
                    sh._store_cached(ref, v)
        book.save(path)
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        for name in os.listdir(tmp):
            os.unlink(os.path.join(tmp, name))
        os.rmdir(tmp)

