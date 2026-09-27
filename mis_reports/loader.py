"""Read the Master Sheet (Domestic) workbook into clean pandas tables.

The workbook's formulas are not consistent from row to row, so we read the
values Excel last calculated and only fall back to recomputing a column
when Excel left it blank (e.g. a file that was never opened in Excel).
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

# canonical field -> header text in the sheet (compared after normalising)
PURCHASE_COLUMNS = {
    "company": "Com.",
    "type": "Type",
    "sub_type": "Sub Type",
    "warehouse": "Warehouse",
    "broker": "Broker",
    "party": "PARTY NAME",
    "gstin": "PARTY GSTN NO",
    "branch": "BRANCH",
    "bill_no": "BILL NO.",
    "bill_date": "BILL DATE",
    "stock_date": "WH In Date",
    "truck_no": "TRUCK NO",
    "commodity": "COMMODITY",
    "hsn": "HSN CODE",
    "no_of_bags": "NO OF BAG",
    "bill_weight": "BILL WEIGHT",
    "qty": "WEIGHT",
    "rate": "RATE",
    "amount": "Amount befor GST",
    "adhat": "Adhat",
    "amc": "AMC",
    "labour": "Labour",
    "transport_pre": "Transporation",
    "wh_load": "WH Load",
    "bags": "Bags",
    "other_pre": "Other",
    "pre_exp": "Total Pre Bill Exp",
    "discount": "Discount",
    "net_amount": "Net Amount befor GST",
    "gst": "GST",
    "bill_amt": "Bill Amt",
    "vatav": "Vatav",
    "final_amt": "Final Amt.",
    "status": "Status",
    "sales_inv": "S Inv",
    "pay_date": "Date",
    "paid": "Amount",
    "tds": "TDS",
    "note": "Debit Note / Other de.",
    "post_exp": "Total Post exp.",
    "storage": "Storage Amt.",
    "brokerage": "Brokerage",
    "sampling": "Sampling Expenses",
    "repacking": "Repacking charges",
    "transport_post": "Transportation",
}

SALES_COLUMNS = {
    "company": "Com",
    "type": "Type",
    "sub_type": "Sub Type",
    "warehouse": "Warehouse",
    "broker": "Broker",
    "party": "PARTY NAME",
    "gstin": "PARTY GSTN NO",
    "branch": "BRANCH",
    "bill_no": "BILL NO.",
    "bill_date": "BILL DATE",
    "stock_date": "Delivery Date",
    "truck_no": "TRUCK NO",
    "commodity": "COMMODITY",
    "hsn": "HSN CODE",
    "no_of_bags": "NO OF BAG",
    "bill_weight": "BILL WEIGHT",
    "qty": "WH Weight",
    "rate": "RATE",
    "amount": "Amount before GST",
    "discount": "Discount",
    "net_amount": "Net Amount befor GST",
    "gst": "GST",
    "bill_amt": "Bill Amt",
    "status": "Status",
    "purchase_inv": "P Inv",
    "pay_date": "Date",
    "paid": "Amount",
    "tds": "TDS",
    "note": "Debit Note / Other de.",
    "post_exp": "Total Post Exp.",
    "brokerage": "Brokerage",
    "loading": "Loading / Unloading",
    "repacking": "Repacking",
}

ORDER_COLUMNS = {
    "contract_no": "Contract No",
    "date": "Date",
    "party": "Party Name",
    "broker": "Broker Name",
    "commodity": "Quality",
    "qty_mt": "Qty Mts",
    "rate": "Rate",
    "bal_qty_mt": "Bal Qty",
    "amount": "AMT",
    "status": "Status",
    "company": "Company Name",
    "branch": "Branch",
    "packing": "Packing",
    "delivery_date": "Delivery Date",
    "delivery_place": "Delivery Place",
    "cancel_qty": "Cancel Qty",
    "revised_qty": "Revised Qty",
    "recd_qty": "Recd Qty",
    "qty_diff": "Qty + / -",
    "recd_date": "Recd Date",
    "bill_date": "Bill Date",
    "bill_no": "Bill No",
    "bill_rate": "BILL RATE",
    "lorry_no": "LORRY NO",
    "bill_weight": "Bill Weight",
    "warehouse": "Warehouse",
}
ORDER_REQUIRED = {"contract_no", "date", "party", "commodity", "qty_mt", "rate", "bal_qty_mt", "amount", "status"}

# Registers of debit notes (purchase side) and credit notes (sales side) kept by the app.
NOTE_SHEETS = {"Purchase": "Debit Notes", "Sales": "Credit Notes"}
NOTE_COLUMNS = {
    "note_no": "Note No",
    "date": "Date",
    "party": "Party",
    "bill_no": "Bill No",
    "bill_row": "Sheet Row",
    "product": "Product",
    "qty": "Qty (kg)",
    "rate": "Rate",
    "taxable": "Taxable Value",
    "gst_pct": "GST %",
    "gst": "GST",
    "other": "Other Charges",
    "total": "Total",
    "reason": "Reason",
}

PURCHASE_PRE_PARTS = ["adhat", "amc", "labour", "transport_pre", "wh_load", "bags", "other_pre"]
PURCHASE_POST_PARTS = ["storage", "brokerage", "sampling", "repacking", "transport_post"]
SALES_POST_PARTS = ["brokerage", "loading", "repacking"]

TEXT_FIELDS = {"company", "type", "sub_type", "warehouse", "broker", "party", "gstin",
               "branch", "bill_no", "commodity", "status", "contract_no", "truck_no", "hsn", "sales_inv",
               "purchase_inv", "packing", "delivery_place", "lorry_no", "note_no", "product", "reason"}
DATE_FIELDS = {"bill_date", "stock_date", "pay_date", "date", "delivery_date", "recd_date"}


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9/.+%]+", " ", str(text).lower()).strip()


def party_key(name) -> str:
    """Key used to group spellings of the same party ('R.R. Impex' / 'R R IMPEX')."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


@dataclass
class MasterData:
    purchase: pd.DataFrame
    sales: pd.DataFrame
    po: pd.DataFrame
    so: pd.DataFrame
    opening_creditors: dict = field(default_factory=dict)  # party_key -> (party name, opening balance)
    opening_debtors: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    debit_notes: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=list(NOTE_COLUMNS)))
    credit_notes: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=list(NOTE_COLUMNS)))


def _find_header_row(raw: pd.DataFrame, marker: str, max_scan: int = 15) -> int:
    for i in range(min(max_scan, len(raw))):
        if any(_norm(v) == _norm(marker) for v in raw.iloc[i].tolist()):
            return i
    raise ValueError(f"Could not find a header row containing '{marker}'")


def _read_table(xls: pd.ExcelFile, sheet: str, columns: dict, marker: str,
                key_field: str, problems: list, required=None) -> pd.DataFrame:
    raw = pd.read_excel(xls, sheet_name=sheet, header=None)
    hdr = _find_header_row(raw, marker)
    headers = [_norm(v) for v in raw.iloc[hdr].tolist()]
    body = raw.iloc[hdr + 1:].reset_index(drop=True)

    out = pd.DataFrame(index=body.index)
    out["source_row"] = body.index + hdr + 2  # 1-based Excel row number
    for fld, header in columns.items():
        want = _norm(header)
        idx = [i for i, h in enumerate(headers) if h == want]
        if idx:
            out[fld] = body.iloc[:, idx[0]]
        else:
            out[fld] = pd.NA
            if required is None or fld in required:
                problems.append(f"{sheet}: column '{header}' not found - treated as blank")

    # every other column (BL No, Exg Rate, Storage Out Date ...) is kept as-is, so nothing typed is lost
    known = {_norm(h) for h in columns.values()}
    others = [(i, str(raw.iloc[hdr, i]).strip()) for i, h in enumerate(headers)
              if h and h != "nan" and h not in known]
    out["_extra"] = [{name: v for i, name in others if (v := _plain(body.iat[r, i])) is not None}
                     for r in range(len(body))]

    out = out[out[key_field].notna() & (out[key_field].astype(str).str.strip() != "")]
    for fld in out.columns:
        if fld == "_extra":
            continue
        if fld in TEXT_FIELDS:
            out[fld] = out[fld].where(out[fld].isna(), out[fld].astype(str).str.strip())
        elif fld in DATE_FIELDS:
            out[fld] = pd.to_datetime(out[fld].map(_as_date), errors="coerce")
        elif fld != "source_row":
            out[fld] = pd.to_numeric(out[fld], errors="coerce")
    return out.reset_index(drop=True)


def _plain(v):
    """A JSON-friendly copy of a cell value: None for blanks, dates as 'YYYY-MM-DD'."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%Y-%m-%d") if v == v.replace(hour=0, minute=0, second=0, microsecond=0) \
            else v.strftime("%Y-%m-%dT%H:%M:%S")
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, str):
        return v if v.strip() else None
    return v


def _as_date(v):
    """Dates may arrive as datetimes, Excel serial numbers or text."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return pd.NaT
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v)) if 1 < v < 100000 else pd.NaT
    return pd.to_datetime(v, errors="coerce", dayfirst=True)


def _fill(df: pd.DataFrame, col: str, fallback: pd.Series) -> None:
    df[col] = df[col].where(df[col].notna(), fallback)


def _complete_purchase(df: pd.DataFrame) -> pd.DataFrame:
    _fill(df, "amount", df["qty"] * df["rate"])
    _fill(df, "pre_exp", df[PURCHASE_PRE_PARTS].sum(axis=1, min_count=1))
    _fill(df, "net_amount", df["amount"].fillna(0) + df["pre_exp"].fillna(0) - df["discount"].fillna(0))
    _fill(df, "bill_amt", df["amount"] + df["gst"].fillna(0))  # Master Sheet: Bill Amt = Amount + GST
    _fill(df, "final_amt", df["bill_amt"] - df["vatav"].fillna(0))
    _fill(df, "post_exp", df[PURCHASE_POST_PARTS].sum(axis=1, min_count=1))
    return df


def _complete_sales(df: pd.DataFrame) -> pd.DataFrame:
    # Master Sheet: Amount before GST = BILL WEIGHT x RATE
    _fill(df, "amount", df["bill_weight"].where(df["bill_weight"].notna(), df["qty"]) * df["rate"])
    _fill(df, "net_amount", df["amount"] - df["discount"].fillna(0))
    _fill(df, "bill_amt", df["amount"] + df["gst"].fillna(0))
    _fill(df, "post_exp", df[SALES_POST_PARTS].sum(axis=1, min_count=1))
    return df


def _read_opening(xls: pd.ExcelFile) -> tuple[dict, dict]:
    """Opening balances typed into the 'Total Debtor Creditor' sheet (col C and M)."""
    if "Total Debtor Creditor" not in xls.sheet_names:
        return {}, {}
    raw = pd.read_excel(xls, sheet_name="Total Debtor Creditor", header=None)
    cred, debt = {}, {}
    for _, row in raw.iloc[3:].iterrows():
        for name_col, bal_col, target in ((1, 2, cred), (11, 12, debt)):
            if raw.shape[1] <= bal_col:
                continue
            name, bal = row.iloc[name_col], pd.to_numeric(row.iloc[bal_col], errors="coerce")
            if pd.notna(name) and str(name).strip() and pd.notna(bal) and bal != 0:
                k = party_key(name)
                target[k] = (target.get(k, (str(name).strip(), 0.0))[0], target.get(k, ("", 0.0))[1] + float(bal))
    return cred, debt


# other names people give the same sheets (compared lower-case, without spaces or punctuation)
SHEET_NAMES = {
    "Purchase": {"purchase", "purchases", "purchasebills", "purchaseregister", "purchaseinvoices"},
    "Sales": {"sales", "sale", "salesbills", "salesregister", "salesinvoices"},
    "PO": {"po", "pos", "purchaseorder", "purchaseorders", "purchasecontracts"},
    "SO": {"so", "sos", "salesorder", "salesorders", "salescontracts"},
    "Debit Notes": {"debitnotes", "debitnote", "dn"},
    "Credit Notes": {"creditnotes", "creditnote", "cn"},
}


def _key(name) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def find_sheets(xls: pd.ExcelFile) -> dict:
    """Which sheet holds what: {'Purchase': 'Purchase', 'Sales': 'sales bills', ...}.
    Names are matched loosely; a purchase / sales sheet with another name is recognised by its headers
    (PARTY NAME with WEIGHT for purchases, with WH Weight for sales)."""
    found = {}
    for sheet in xls.sheet_names:
        for kind, names in SHEET_NAMES.items():
            if kind not in found and _key(sheet) in names:
                found[kind] = sheet
    for kind, header in (("Purchase", "WEIGHT"), ("Sales", "WH Weight")):
        if kind in found:
            continue
        for sheet in xls.sheet_names:
            if sheet in found.values():
                continue
            top = pd.read_excel(xls, sheet_name=sheet, header=None, nrows=15)
            cells = {_norm(v) for v in top.to_numpy().ravel() if pd.notna(v)}
            if _norm("PARTY NAME") in cells and _norm(header) in cells:
                found[kind] = sheet
                break
    return found


def _empty(columns: dict) -> pd.DataFrame:
    return pd.DataFrame(columns=["source_row", *columns, "_extra"])


def load_master(source) -> MasterData:
    """source: a file path or file-like object for the Master Sheet workbook."""
    problems: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # openpyxl warns about data-validation extensions
        xls = pd.ExcelFile(source, engine="openpyxl")
        found = find_sheets(xls)
        missing = [s for s in ("Purchase", "Sales") if s not in found]
        if missing:
            raise ValueError(f"Workbook is missing required sheet(s): {', '.join(missing)}")

        purchase = _complete_purchase(
            _read_table(xls, found["Purchase"], PURCHASE_COLUMNS, "PARTY NAME", "party", problems))
        sales = _complete_sales(
            _read_table(xls, found["Sales"], SALES_COLUMNS, "PARTY NAME", "party", problems))

        orders = {}
        for sheet in ("PO", "SO"):
            if sheet in found:
                df = _read_table(xls, found[sheet], ORDER_COLUMNS, "Contract No", "commodity", problems,
                                 ORDER_REQUIRED)
                orders[sheet] = df[df["qty_mt"].notna()].reset_index(drop=True)
            else:
                orders[sheet] = _empty(ORDER_COLUMNS)
        opening_c, opening_d = _read_opening(xls)
        notes = {}
        for kind, sheet in NOTE_SHEETS.items():
            if sheet in found:
                notes[kind] = _read_table(xls, found[sheet], NOTE_COLUMNS, "Note No", "party", problems)
            else:
                notes[kind] = _empty(NOTE_COLUMNS)

    if purchase[["qty", "amount"]].isna().all().all() and len(purchase):
        problems.append("Purchase sheet has no calculated amounts - open and save the file in Excel first")

    return MasterData(purchase, sales, orders["PO"], orders["SO"], opening_c, opening_d, problems,
                      notes["Purchase"], notes["Sales"])
