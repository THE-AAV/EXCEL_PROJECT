"""Record business transactions straight into the Master Sheet.

Flow: Purchase Order -> Purchase Invoice -> Debit Note -> Expenses -> Payment
      Sales Order    -> Sales Invoice    -> Credit Note -> Receipt

Every save first copies the file to a 'backups' folder, then writes only the
cells it needs, then adds a line to the activity log.
"""
from __future__ import annotations

import csv
import os
import re
import shutil
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from .loader import NOTE_COLUMNS, NOTE_SHEETS, ORDER_COLUMNS, PURCHASE_COLUMNS, SALES_COLUMNS, _norm
from .xlsx_edit import Book, backup, from_pattern, split_ref, usual_formulas

ORDER_WRITE_COLUMNS = {k: v for k, v in ORDER_COLUMNS.items() if k not in ("revised_qty", "bal_qty_mt", "amount")}

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

PRE_BILL_FIELDS = ["adhat", "amc", "labour", "transport_pre", "wh_load", "bags", "other_pre", "discount"]

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

NOTE_REASONS = ["Goods returned", "Weight shortage", "Quality claim", "Rate difference", "Other"]


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
            for ref in sh.cells:
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

    # ---- numbering
    def next_contract_no(self, kind: str):
        book = self._open()
        sh, hdr, cols, last, used = self._layout(book, kind)
        return next_number([sh.value(f"{cols['contract_no']}{x}") for x in used])

    def next_note_no(self, kind: str):
        book = self._open()
        first = "DN-0001" if kind == "Purchase" else "CN-0001"
        name = NOTE_SHEETS[kind]
        if name not in book.sheet_parts:
            return first
        sh = book.sheet(name)
        return next_number([sh.value(f"A{r}") for r in sorted(sh.rows) if r > 1], first)

    # ---- orders
    def add_order(self, kind: str, fields: dict, contract_no=None) -> int:
        """kind 'PO' or 'SO'. fields use ORDER_WRITE_COLUMNS keys; qty_mt and rate required.
        contract_no: the user's own number, or None to number it automatically."""
        _require(fields, ["party", "commodity", "qty_mt", "rate", "date"])
        book = self._open()
        sh, hdr, cols, last, used = self._layout(book, kind)
        r = last + 1
        tmpl = last if last > hdr else None
        existing = [sh.value(f"{cols['contract_no']}{x}") for x in used]
        if _filled(contract_no):
            contract_no = _clean_number(contract_no)
            if any(_same_number(contract_no, e) for e in existing):
                raise EntryError(f"Contract No. {contract_no} is already used in the {kind} sheet")
        else:
            contract_no = next_number(existing)
        values = {"cancel_qty": 0, "recd_qty": 0, "qty_diff": 0, **fields, "contract_no": contract_no}
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
                  f"Contract {contract_no}: {fields['commodity']} {fields['qty_mt']:g} MT @ {fields['rate']:g}")
        return r

    # ---- invoices
    def add_invoice(self, kind: str, fields: dict, gst_pct: float = 5.0, order_row: int | None = None) -> int:
        """Single-item invoice; see add_invoice_lines."""
        item_keys = ("commodity", "qty", "rate", "hsn", "no_of_bags", "bill_weight")
        header = {k: v for k, v in fields.items() if k not in item_keys}
        line = {k: fields.get(k) for k in item_keys}
        line.update(gst_pct=gst_pct, order_row=order_row)
        return self.add_invoice_lines(kind, header, [line])[0]

    def add_invoice_lines(self, kind: str, header: dict, lines: list[dict], expenses: dict | None = None) -> list[int]:
        """One bill with one or more items. Each item becomes a row in the Purchase / Sales sheet.

        header:   party, bill_no, bill_date, stock_date, truck_no, company, type, sub_type, warehouse, broker,
                  gstin, branch
        lines:    commodity, qty (kg), rate, gst_pct, and optionally order_row (the PO / SO row it is against),
                  link_row (Sales only: Purchase sheet row of the bill the goods came from), hsn, no_of_bags,
                  bill_weight
        expenses: pre-bill expenses and discount for the whole bill ({field: amount}); they are split over
                  the items in proportion to their value.
        """
        lines = [dict(l) for l in lines if l and (_filled(l.get("commodity")) or (l.get("qty") or 0) > 0)]
        if not lines:
            raise EntryError("Add at least one item")
        _require(header, ["party", "bill_date"])
        for i, line in enumerate(lines, 1):
            try:
                _require(line, ["commodity", "qty", "rate"])
            except EntryError as exc:
                raise EntryError(f"Item {i}: {exc}") from None
        shares = {f: split_by_value(float(v), [l["qty"] * l["rate"] for l in lines])
                  for f, v in (expenses or {}).items() if v}

        book = self._open()
        sh, hdr, cols, last, used = self._layout(book, kind)
        for f in shares:
            if f not in cols:
                raise EntryError(f"Column for '{f}' not found in the {kind} sheet")
        tmpl = last if last > hdr else None
        base_pattern = usual_formulas(sh, used[-30:], _all_columns(sh, hdr))
        rows = []
        for i, line in enumerate(lines):
            r = last + 1 + i
            pattern = dict(base_pattern)
            for f, tpl in FIXED_FORMULAS.get(kind, {}).items():
                if f in cols:
                    try:
                        pattern[cols[f]] = tpl.format(g=_fmt(line.get("gst_pct", 5.0)), **cols)
                    except KeyError:
                        pass
            values = {**header, **{k: v for k, v in line.items() if k not in ("gst_pct", "order_row", "link_row")}}
            values["bill_weight"] = values.get("bill_weight") or line["qty"]
            for f, parts in shares.items():
                values[f] = parts[i]
            if kind == "Sales" and line.get("link_row"):
                values["purchase_inv"] = self._link_purchase(book, int(line["link_row"]), header.get("bill_no"))
            for f, col in cols.items():
                if f in values and _filled(values[f]):
                    sh.set(f"{col}{r}", values[f], template_row=tmpl)
                elif col in pattern and f != "rate":
                    sh.set_formula(f"{col}{r}", from_pattern(pattern[col], r), template_row=tmpl)
                elif tmpl:
                    sh.set(f"{col}{r}", None, template_row=tmpl)
            for col, pat in pattern.items():   # formula columns without a field name (SR.NO., PSN, due days)
                if col not in cols.values() and not _filled(sh.formula(f"{col}{r}")):
                    sh.set_formula(f"{col}{r}", from_pattern(pat, r), template_row=tmpl)
            sh.recalc_row(r)
            if line.get("order_row"):
                self._receive_on_order(book, "PO" if kind == "Purchase" else "SO", int(line["order_row"]),
                                       header, line)
            rows.append(r)
        book.last_data_row[sh.name] = rows[-1]
        self._save(book)
        for r, line in zip(rows, lines):
            self._log(f"{kind} Invoice", sh.name, r, header["party"], line["qty"] * line["rate"],
                      f"Bill {header.get('bill_no') or '-'}: {line['commodity']} {line['qty']:g} kg @ {line['rate']:g}"
                      + (f" (order row {line['order_row']})" if line.get("order_row") else "")
                      + (f" (from purchase row {line['link_row']})" if line.get("link_row") else ""))
        return rows

    def _receive_on_order(self, book, okind, order_row, header, line):
        osh, _, ocols, _, oused = self._layout(book, okind)
        _check_row(order_row, oused)
        ref = f"{ocols['recd_qty']}{order_row}"
        osh.set(ref, round((osh.value(ref) or 0) + line["qty"] / 1000, 6))
        for f, v in (("recd_date", header.get("stock_date") or header["bill_date"]),
                     ("bill_date", header["bill_date"]), ("bill_rate", line["rate"]),
                     ("lorry_no", header.get("truck_no")), ("bill_weight", line["qty"])):
            if f in ocols and _filled(v) and not _filled(osh.value(f"{ocols[f]}{order_row}")):
                osh.set(f"{ocols[f]}{order_row}", v)
        if "bill_no" in ocols and _filled(header.get("bill_no")):
            ref = f"{ocols['bill_no']}{order_row}"
            osh.set(ref, _append_list(osh.value(ref), header["bill_no"]))
        osh.recalc_row(order_row)

    def _link_purchase(self, book, purchase_row: int, sales_bill_no) -> str:
        """Note the sales bill on the purchase row ('S Inv') and return the purchase bill no. for 'P Inv'."""
        psh, _, pcols, _, pused = self._layout(book, "Purchase")
        _check_row(purchase_row, pused)
        if "sales_inv" in pcols and _filled(sales_bill_no):
            ref = f"{pcols['sales_inv']}{purchase_row}"
            psh.set(ref, _append_list(psh.value(ref), sales_bill_no))
        bill = psh.value(f"{pcols['bill_no']}{purchase_row}")
        return _text(bill) if _filled(bill) else f"Purchase row {purchase_row}"

    # ---- debit / credit notes
    def add_note(self, kind: str, row: int, amount: float) -> str:
        """Amount-only debit note (kind 'Purchase') or credit note (kind 'Sales') against a bill row."""
        return self.add_note_detailed(kind, row, {"taxable": amount, "gst_pct": 0, "reason": "Other"})

    def add_note_detailed(self, kind: str, row: int, note: dict) -> str:
        """Debit note (kind 'Purchase') / credit note (kind 'Sales') with quantity, tax and other charges.

        note: note_no (None = automatic), date, qty (kg; 0 for amount-only notes), rate, taxable (defaults
              to qty x rate), gst_pct, other (other charges / expenses), reason.
        The note is listed in the 'Debit Notes' / 'Credit Notes' sheet, and its total is added to the
        bill's 'Debit Note / Other de.' column, which reduces the party balance.
        """
        qty = float(note.get("qty") or 0)
        rate = float(note.get("rate") or 0)
        taxable = float(note["taxable"]) if _filled(note.get("taxable")) else _round2(qty * rate)
        gst_pct = float(note.get("gst_pct") or 0)
        other = float(note.get("other") or 0)
        if qty < 0 or taxable < 0 or other < 0 or gst_pct < 0:
            raise EntryError("Amounts cannot be negative")
        gst = _round2(taxable * gst_pct / 100)
        total = _round2(taxable + gst + other)
        if total <= 0:
            raise EntryError("Enter a quantity and rate, or an amount")

        book = self._open()
        sh, hdr, cols, last, used = self._layout(book, kind)
        _check_row(row, used)
        bill_qty = sh.value(f"{cols['qty']}{row}") or 0
        if qty > bill_qty + 0.001:
            raise EntryError(f"Quantity {qty:g} kg is more than the {bill_qty:g} kg on the bill")
        head_cell = sh.cells.get(f"{cols['party']}{hdr}")
        reg = book.add_sheet(NOTE_SHEETS[kind], list(NOTE_COLUMNS.values()),
                             header_style=head_cell.get("s") if head_cell is not None else None)
        existing = [reg.value(f"A{r}") for r in sorted(reg.rows) if r > 1]
        note_no = note.get("note_no")
        if _filled(note_no):
            note_no = _clean_number(note_no)
            if any(_same_number(note_no, e) for e in existing):
                raise EntryError(f"Note No. {note_no} is already used")
        else:
            note_no = next_number(existing, "DN-0001" if kind == "Purchase" else "CN-0001")
        party = sh.value(f"{cols['party']}{row}")
        bill_no = _text(sh.value(f"{cols['bill_no']}{row}"))
        r = max(reg.rows) + 1
        values = [note_no, note.get("date") or date.today(), party, bill_no, row,
                  sh.value(f"{cols['commodity']}{row}"), qty, rate, taxable, gst_pct]
        for col, v in zip("ABCDEFGHIJ", values):
            reg.set(f"{col}{r}", v)
        reg.set_formula(f"K{r}", f"ROUND(I{r}*J{r}/100,2)")
        reg.set(f"L{r}", other)
        reg.set_formula(f"M{r}", f"I{r}+K{r}+L{r}")
        reg.set(f"N{r}", note.get("reason") or "")
        reg.recalc_row(r)

        ref = f"{cols['note']}{row}"
        sh.set(ref, _round2((sh.value(ref) or 0) + total))
        sh.recalc_row(row)
        self._save(book)
        self._log("Debit Note" if kind == "Purchase" else "Credit Note", sh.name, row, party, total,
                  f"{note_no} on bill {bill_no}: {qty:g} kg, taxable {taxable:,.2f}, GST {gst:,.2f}, "
                  f"other {other:,.2f} ({note.get('reason') or '-'})")
        return note_no

    # ---- expenses, payments
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
        self._log("Expenses", sh.name, row, sh.value(f"{cols['party']}{row}"),
                  sum(float(v or 0) for v in changes.values()), ", ".join(f"{k}={v}" for k, v in changes.items()))

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
                    sh.set(ref, _round2((sh.value(ref) or 0) + add))
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


# --------------------------------------------------------------------------- numbering
def next_number(existing, first="1"):
    """Next number in the same style as the ones already used.

    '7' -> 8, 'PO/26-27/009' -> 'PO/26-27/010'. When several numbers share a pattern, the part that
    changes from one to the next is counted up, so 'SCPL/CH13/26-27' becomes 'SCPL/CH14/26-27'."""
    vals = [_text(v).strip() for v in existing if _filled(v)]
    vals = [v for v in vals if re.search(r"\d", v)]
    if not vals:
        return int(first) if str(first).isdigit() else first
    if all(re.fullmatch(r"\d+(\.0+)?", v) for v in vals):
        return int(max(float(v) for v in vals)) + 1
    last = vals[-1]
    shape = re.sub(r"\d+", "#", last)
    groups = [re.findall(r"\d+", v) for v in vals if re.sub(r"\d+", "#", v) == shape]
    n = len(groups[0])
    varying = [i for i in range(n) if len({g[i] for g in groups}) > 1]
    if varying:
        idx = varying[-1]
    else:
        idx = n - 1
        if re.search(r"\d{2}-\d{2}$", last) and n >= 3:   # ends with a financial year like 26-27
            idx = n - 3
    top = max(int(g[idx]) for g in groups) + 1
    a, b = [m.span() for m in re.finditer(r"\d+", last)][idx]
    return last[:a] + str(top).zfill(b - a) + last[b:]


def _clean_number(v):
    v = str(v).strip()
    return int(v) if re.fullmatch(r"\d+", v) else v


def _same_number(a, b) -> bool:
    return _filled(b) and _text(a).strip().lower() == _text(b).strip().lower()


# --------------------------------------------------------------------------- small helpers
def _text(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return "" if v is None else str(v)


def _append_list(current, item) -> str:
    items = [x.strip() for x in _text(current).split(",") if x.strip()]
    if _text(item) not in items:
        items.append(_text(item))
    return ", ".join(items)


def split_by_value(total: float, weights: list[float]) -> list[float]:
    """Split an amount over items in proportion to their value; the last item takes the rounding."""
    w = sum(weights)
    if w <= 0:
        weights, w = [1.0] * len(weights), float(len(weights))
    parts = [_round2(total * x / w) for x in weights[:-1]]
    return parts + [_round2(total - sum(parts))]


def _round2(v: float) -> float:
    return float(Decimal(repr(float(v))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _filled(v) -> bool:
    return v is not None and not (isinstance(v, str) and not v.strip()) and v == v


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
    shutil.copy2(latest, path)
    os.remove(latest)
    return latest.name
