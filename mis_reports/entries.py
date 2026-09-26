"""Record business transactions straight into the Master Sheet.

Flow: Purchase Order -> Purchase Invoice -> Debit Note -> Expenses -> Payment
      Sales Order    -> Sales Invoice    -> Credit Note -> Receipt

Every save first copies the file to a 'backups' folder, then writes only the
cells it needs, then adds a line to the activity log.
"""
from __future__ import annotations

import csv
import os
from datetime import date, datetime
from pathlib import Path

from .loader import ORDER_COLUMNS, PURCHASE_COLUMNS, SALES_COLUMNS, _norm
from .xlsx_edit import Book, backup, from_pattern, split_ref, usual_formulas

ORDER_WRITE_COLUMNS = {
    **ORDER_COLUMNS,
    "company": "Company Name",
    "branch": "Branch",
    "packing": "Packing",
    "delivery_date": "Delivery Date",
    "delivery_place": "Delivery Place",
    "cancel_qty": "Cancel Qty",
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

SHEETS = {
    # kind: (sheet name, header marker, column map, key field that marks a used row)
    "Purchase": ("Purchase", "PARTY NAME", PURCHASE_COLUMNS, "party"),
    "Sales": ("Sales", "PARTY NAME", SALES_COLUMNS, "party"),
    "PO": ("PO", "Contract No", ORDER_WRITE_COLUMNS, "commodity"),
    "SO": ("SO", "Contract No", ORDER_WRITE_COLUMNS, "commodity"),
}

# Formulas used for new invoice rows where the sheet's own rows are not a reliable guide.
# {g} is replaced by the GST rate. Other formula columns copy the pattern most recent rows use.
FIXED_FORMULAS = {
    "Purchase": {"amount": "{qty}[0]*{rate}[0]", "pre_exp": "SUM({adhat}[0]:{other_pre}[0])",
                 "net_amount": "{amount}[0]+{pre_exp}[0]-{discount}[0]", "gst": "{net_amount}[0]*{g}%",
                 "final_amt": "{bill_amt}[0]-{vatav}[0]"},
    "Sales": {"gst": "{amount}[0]*{g}%"},
}

EXPENSE_FIELDS = {
    "Purchase": {
        "Pre-bill expenses (added to cost)": ["adhat", "amc", "labour", "transport_pre", "wh_load", "bags",
                                              "other_pre"],
        "Deductions": ["discount", "vatav"],
        "Post-bill expenses": ["storage", "brokerage", "sampling", "repacking", "transport_post"],
    },
    "Sales": {
        "Deductions": ["discount"],
        "Post-bill expenses": ["brokerage", "loading", "repacking"],
    },
}


class EntryError(ValueError):
    pass


class MasterFile:
    def __init__(self, path, backup_dir=None, log_path=None):
        self.path = Path(path)
        self.backup_dir = Path(backup_dir) if backup_dir else self.path.parent / "backups"
        self.log_path = Path(log_path) if log_path else self.path.parent / "activity_log.csv"

    # ---- helpers
    def _open(self):
        return Book(self.path)

    @staticmethod
    def _layout(book: Book, kind: str):
        sheet_name, marker, colmap, key = SHEETS[kind]
        sh = book.sheet(sheet_name)
        hdr = None
        for r in range(1, 16):
            for ref, c in sh.cells.items():
                if split_ref(ref)[1] == r and _norm(sh.value(ref) or "") == _norm(marker):
                    hdr = r
                    break
            if hdr:
                break
        if hdr is None:
            raise EntryError(f"Header row not found in sheet '{sheet_name}'")
        by_header = {}
        for ref in sorted(sh.cells, key=lambda x: (len(split_ref(x)[0]), split_ref(x)[0])):
            col, r = split_ref(ref)
            if r == hdr and sh.value(ref) is not None:
                by_header.setdefault(_norm(sh.value(ref)), col)
        cols = {f: by_header[_norm(h)] for f, h in colmap.items() if _norm(h) in by_header}
        used = [r for r in sh.rows if r > hdr and _filled(sh.value(f"{cols[key]}{r}"))]
        last = max(used) if used else hdr
        return sh, hdr, cols, last, used

    def _log(self, action, sheet, row, party, amount, details=""):
        new = not self.log_path.exists()
        with self.log_path.open("a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["When", "Action", "Sheet", "Row", "Party", "Amount", "Details"])
            w.writerow([f"{datetime.now():%Y-%m-%d %H:%M:%S}", action, sheet, row, party,
                        round(float(amount or 0), 2), details])

    def _save(self, book: Book):
        backup(self.path, self.backup_dir)
        book.save(self.path)

    # ---- orders
    def add_order(self, kind: str, fields: dict) -> int:
        """kind 'PO' or 'SO'. fields use ORDER_WRITE_COLUMNS keys; qty_mt and rate required."""
        _require(fields, ["party", "commodity", "qty_mt", "rate", "date"])
        book = self._open()
        sh, hdr, cols, last, used = self._layout(book, kind)
        r = last + 1
        tmpl = last if last > hdr else None
        nums = [int(v) for v in (sh.value(f"{cols['contract_no']}{x}") for x in used) if _is_num(v)]
        values = {"contract_no": (max(nums) + 1) if nums else 1, "cancel_qty": 0, "recd_qty": 0,
                  "qty_diff": 0, **fields}
        formulas = usual_formulas(sh, used[-30:], _all_columns(sh, hdr))
        for f, col in cols.items():
            if f in values and _filled(values[f]):
                sh.set(f"{col}{r}", values[f], template_row=tmpl)
            elif col in formulas:
                sh.set_formula(f"{col}{r}", from_pattern(formulas[col], r), template_row=tmpl)
        for col, pat in formulas.items():
            if col not in cols.values():
                sh.set_formula(f"{col}{r}", from_pattern(pat, r), template_row=tmpl)
        sh.recalc_row(r)
        book.last_data_row[sh.name] = r
        self._save(book)
        self._log(f"{'Purchase' if kind == 'PO' else 'Sales'} Order", sh.name, r, fields["party"],
                  fields["qty_mt"] * 1000 * fields["rate"],
                  f"Contract {values['contract_no']}: {fields['commodity']} {fields['qty_mt']} MT @ {fields['rate']}")
        return r

    # ---- invoices
    def add_invoice(self, kind: str, fields: dict, gst_pct: float = 5.0, order_row: int | None = None) -> int:
        """kind 'Purchase' or 'Sales'. fields use the loader column keys (party, commodity, qty, rate ...)."""
        _require(fields, ["party", "commodity", "qty", "rate", "bill_date"])
        book = self._open()
        sh, hdr, cols, last, used = self._layout(book, kind)
        r = last + 1
        tmpl = last if last > hdr else None
        recent = used[-30:]
        pattern = usual_formulas(sh, recent, _all_columns(sh, hdr))
        for f, tpl in FIXED_FORMULAS.get(kind, {}).items():
            if f in cols:
                try:
                    pattern[cols[f]] = tpl.format(g=_fmt(gst_pct), **cols)
                except KeyError:
                    pass
        values = dict(fields)
        values.setdefault("bill_weight", fields["qty"])
        allcols = cols
        for f, col in allcols.items():
            if f in values and _filled(values[f]):
                sh.set(f"{col}{r}", values[f], template_row=tmpl)
            elif col in pattern and f not in ("rate",):
                sh.set_formula(f"{col}{r}", from_pattern(pattern[col], r), template_row=tmpl)
            elif tmpl:
                sh.set(f"{col}{r}", None, template_row=tmpl)
        # remaining formula columns without a field name (e.g. SR.NO., PSN, due days)
        for col, pat in pattern.items():
            if col not in cols.values() and not _filled(sh.formula(f"{col}{r}")):
                sh.set_formula(f"{col}{r}", from_pattern(pat, r), template_row=tmpl)
        sh.recalc_row(r)
        book.last_data_row[sh.name] = r

        if order_row:
            okind = "PO" if kind == "Purchase" else "SO"
            osh, _, ocols, _, _ = self._layout(book, okind)
            ref = f"{ocols['recd_qty']}{order_row}"
            osh.set(ref, (osh.value(ref) or 0) + fields["qty"] / 1000)
            for f, v in (("recd_date", fields.get("stock_date") or fields["bill_date"]),
                         ("bill_date", fields["bill_date"]), ("bill_no", fields.get("bill_no")),
                         ("bill_rate", fields["rate"]), ("lorry_no", fields.get("truck_no")),
                         ("bill_weight", fields["qty"])):
                if f in ocols and _filled(v) and not _filled(osh.value(f"{ocols[f]}{order_row}")):
                    osh.set(f"{ocols[f]}{order_row}", v)
            osh.recalc_row(order_row)
        self._save(book)
        self._log(f"{kind} Invoice", sh.name, r, fields["party"], fields["qty"] * fields["rate"],
                  f"Bill {fields.get('bill_no') or '-'}: {fields['commodity']} {fields['qty']} kg @ {fields['rate']}"
                  + (f" (order row {order_row})" if order_row else ""))
        return r

    # ---- notes, expenses, payments
    def add_note(self, kind: str, row: int, amount: float) -> None:
        """Debit note (kind 'Purchase') or credit note (kind 'Sales') against a bill row."""
        if amount <= 0:
            raise EntryError("Amount must be more than zero")
        book = self._open()
        sh, hdr, cols, last, used = self._layout(book, kind)
        _check_row(row, used)
        ref = f"{cols['note']}{row}"
        sh.set(ref, round((sh.value(ref) or 0) + amount, 2))
        sh.recalc_row(row)
        self._save(book)
        self._log("Debit Note" if kind == "Purchase" else "Credit Note", sh.name, row,
                  sh.value(f"{cols['party']}{row}"), amount,
                  "Bill " + str(sh.value(f"{cols['bill_no']}{row}")))

    def set_expenses(self, kind: str, row: int, changes: dict) -> None:
        """changes: {field: new amount}. Only the given fields are written."""
        if not changes:
            raise EntryError("Nothing changed")
        book = self._open()
        sh, hdr, cols, last, used = self._layout(book, kind)
        _check_row(row, used)
        for f, v in changes.items():
            if f not in cols:
                raise EntryError(f"Column for '{f}' not found")
            sh.set(f"{cols[f]}{row}", float(v) if _filled(v) else None)
        # make sure totals include the expense columns
        for total in ("pre_exp", "post_exp"):
            if total in cols and not sh.formula(f"{cols[total]}{row}"):
                pat = usual_formulas(sh, used[-30:], [cols[total]]).get(cols[total])
                if pat:
                    sh.set_formula(f"{cols[total]}{row}", from_pattern(pat, row))
        sh.recalc_row(row)
        self._save(book)
        self._log("Expenses", sh.name, row, sh.value(f"{cols['party']}{row}"), sum(float(v or 0) for v in changes.values()),
                  ", ".join(f"{k}={v}" for k, v in changes.items()))

    def add_settlement(self, kind: str, when: date, allocations: list[tuple[int, float, float]],
                       outstanding: dict | None = None) -> None:
        """Payment (kind 'Purchase') or receipt (kind 'Sales').
        allocations: [(bill row, amount, tds)]. outstanding: {row: amount due before this entry} used to
        mark bills fully settled as Paid / Recd."""
        allocations = [(r, float(a or 0), float(t or 0)) for r, a, t in allocations if (a or 0) > 0 or (t or 0) > 0]
        if not allocations:
            raise EntryError("Enter an amount against at least one bill")
        book = self._open()
        sh, hdr, cols, last, used = self._layout(book, kind)
        done = "Paid" if kind == "Purchase" else "Recd"
        party = None
        for r, amt, tds in allocations:
            _check_row(r, used)
            party = sh.value(f"{cols['party']}{r}")
            for f, add in (("paid", amt), ("tds", tds)):
                ref = f"{cols[f]}{r}"
                if add:
                    sh.set(ref, round((sh.value(ref) or 0) + add, 2))
            sh.set(f"{cols['pay_date']}{r}", when)
            if outstanding and r in outstanding and outstanding[r] - amt - tds <= 1:
                sh.set(f"{cols['status']}{r}", done)
            sh.recalc_row(r)
        self._save(book)
        total = sum(a for _, a, _ in allocations)
        self._log("Payment" if kind == "Purchase" else "Receipt", sh.name,
                  ", ".join(str(r) for r, _, _ in allocations), party, total,
                  f"TDS {sum(t for _, _, t in allocations):,.2f} on {when:%d-%m-%Y}")

    def read_log(self, limit: int = 50) -> list[dict]:
        if not self.log_path.exists():
            return []
        with self.log_path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        return rows[::-1][:limit]


def _filled(v) -> bool:
    return v is not None and not (isinstance(v, str) and not v.strip()) and v == v


def _is_num(v) -> bool:
    try:
        float(v)
        return v is not None and not isinstance(v, bool)
    except (TypeError, ValueError):
        return False


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def _all_columns(sheet, hdr: int) -> list[str]:
    return sorted({split_ref(ref)[0] for ref in sheet.cells if split_ref(ref)[1] == hdr},
                  key=lambda c: (len(c), c))


def _require(fields: dict, keys: list[str]):
    missing = [k for k in keys if not _filled(fields.get(k)) or (isinstance(fields.get(k), (int, float))
                                                                    and k in ("qty", "qty_mt", "rate")
                                                                    and fields[k] <= 0)]
    if missing:
        names = {"party": "Party", "commodity": "Product", "qty": "Quantity", "qty_mt": "Quantity",
                 "rate": "Rate", "bill_date": "Bill date", "date": "Date"}
        raise EntryError("Please fill in: " + ", ".join(names.get(k, k) for k in missing))


def _check_row(row: int, used: list[int]):
    if row not in used:
        raise EntryError(f"Row {row} is not a bill in the sheet")


def working_file(folder: Path) -> Path | None:
    files = [p for p in Path(folder).glob("*.xls*") if not p.name.startswith("~$")]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def restore_latest_backup(path: Path, backup_dir: Path | None = None) -> str | None:
    backup_dir = Path(backup_dir) if backup_dir else Path(path).parent / "backups"
    base = Path(path).stem + "__"
    files = sorted(f for f in os.listdir(backup_dir) if f.startswith(base)) if backup_dir.exists() else []
    if not files:
        return None
    latest = backup_dir / files[-1]
    import shutil
    shutil.copy2(latest, path)
    os.remove(latest)
    return latest.name
