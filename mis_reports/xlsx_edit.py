"""Surgical editing of the Master Sheet .xlsx.

Libraries such as openpyxl rewrite the whole workbook on save and silently drop
things this workbook depends on (dynamic-array formulas in 'masters', data
validation dropdowns). This module instead edits only the worksheet XML of the
rows we touch and copies every other part of the file byte-for-byte.

Formula cells we create or change get a calculated value stored with them, so
the reports can read the file straight away; Excel also recalculates everything
the next time the file is opened.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from collections import Counter
from datetime import date, datetime

from lxml import etree

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_RNS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


class FileLockedError(RuntimeError):
    """The workbook is open in Excel (Windows locks it), so it cannot be saved."""


# --------------------------------------------------------------------------- cell references
def col_to_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def num_to_col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_ref(ref: str) -> tuple[str, int]:
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    return m.group(1), int(m.group(2))


_REF = re.compile(r"(?<![A-Za-z0-9_.])(\$?)([A-Z]{1,3})(\$?)([0-9]+)(?![0-9A-Za-z_(])")


def _outside_strings(formula: str, fn) -> str:
    parts = re.split(r'("(?:[^"]|"")*")', formula)
    return "".join(p if i % 2 else fn(p) for i, p in enumerate(parts))


def translate(formula: str, drow: int, dcol: int = 0) -> str:
    """Move a formula the way Excel's fill-down / copy does (relative refs shift, $ refs stay)."""
    def shift(m):
        cabs, col, rabs, row = m.groups()
        if not cabs and dcol:
            col = num_to_col(col_to_num(col) + dcol)
        if not rabs:
            row = str(int(row) + drow)
        return f"{cabs}{col}{rabs}{row}"
    return _outside_strings(formula, lambda s: _REF.sub(shift, s))


def relative_pattern(formula: str, row: int) -> str:
    """Formula with row numbers replaced by offsets, used to find the usual formula of a column."""
    def rel(m):
        cabs, col, rabs, r = m.groups()
        return f"{cabs}{col}{rabs}{r}" if rabs else f"{cabs}{col}[{int(r) - row}]"
    return _outside_strings(formula, lambda s: _REF.sub(rel, s))


def from_pattern(pattern: str, row: int) -> str:
    return re.sub(r"([A-Z]{1,3})\[(-?\d+)\]", lambda m: f"{m.group(1)}{row + int(m.group(2))}", pattern)


def excel_serial(d) -> float:
    if isinstance(d, datetime):
        delta = d - datetime(1899, 12, 30)
        return delta.days + delta.seconds / 86400
    return float((d - date(1899, 12, 30)).days)


# --------------------------------------------------------------------------- tiny formula evaluator
class Unsupported(Exception):
    pass


_TOKEN = re.compile(r"""\s*(?:
    (?P<str>"(?:[^"]|"")*")|
    (?P<num>\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)|
    (?P<range>\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+)|
    (?P<ref>\$?[A-Z]{1,3}\$?\d+(?![\w(]))|
    (?P<func>[A-Z][A-Z0-9.]*)\(|
    (?P<bool>TRUE|FALSE)(?![\w(])|
    (?P<op><>|<=|>=|[-+*/^&=<>%(),])
)""", re.X)


def _tokens(formula: str):
    pos, out = 0, []
    while pos < len(formula):
        m = _TOKEN.match(formula, pos)
        if not m or m.end() == pos:
            if formula[pos:].strip() == "":
                break
            raise Unsupported(formula[pos:])
        pos = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
    return out


class _Eval:
    """Recursive-descent evaluator for simple same-sheet formulas (arithmetic, SUM, ROUND, IF...)."""
    FUNCS = {"SUM", "ROUND", "IF", "MAX", "MIN", "ABS", "AND", "OR", "IFERROR", "ROUNDUP", "ROUNDDOWN"}

    def __init__(self, formula, getter):
        self.t = _tokens(formula)
        self.i = 0
        self.get = getter

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, val=None):
        tok = self.peek()
        if val is not None and tok[1] != val:
            raise Unsupported(f"expected {val}")
        self.i += 1
        return tok

    def run(self):
        v = self.compare()
        if self.i != len(self.t):
            raise Unsupported("trailing tokens")
        return v

    def compare(self):
        a = self.concat()
        while self.peek()[1] in ("=", "<>", "<", ">", "<=", ">="):
            op = self.take()[1]
            b = self.concat()
            a = {"=": lambda: _eq(a, b), "<>": lambda: not _eq(a, b), "<": lambda: _num(a) < _num(b),
                 ">": lambda: _cmp_gt(a, b), "<=": lambda: _num(a) <= _num(b),
                 ">=": lambda: _num(a) >= _num(b)}[op]()
        return a

    def concat(self):
        a = self.add()
        while self.peek()[1] == "&":
            self.take()
            a = f"{_text(a)}{_text(self.add())}"
        return a

    def add(self):
        a = self.mul()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            b = self.mul()
            a = _num(a) + _num(b) if op == "+" else _num(a) - _num(b)
        return a

    def mul(self):
        a = self.power()
        while self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            b = self.power()
            if op == "/" and _num(b) == 0:
                raise Unsupported("#DIV/0!")
            a = _num(a) * _num(b) if op == "*" else _num(a) / _num(b)
        return a

    def power(self):
        a = self.unary()
        while self.peek()[1] == "^":
            self.take()
            a = _num(a) ** _num(self.unary())
        return a

    def unary(self):
        if self.peek()[1] in ("-", "+"):
            op = self.take()[1]
            v = _num(self.unary())
            return -v if op == "-" else v
        v = self.atom()
        while self.peek()[1] == "%":
            self.take()
            v = _num(v) / 100
        return v

    def atom(self):
        kind, val = self.take()
        if kind == "num":
            return float(val)
        if kind == "str":
            return val[1:-1].replace('""', '"')
        if kind == "bool":
            return val == "TRUE"
        if kind == "ref":
            return self.get(val.replace("$", ""))
        if kind == "range":
            return _Range(val.replace("$", ""), self.get)
        if val == "(":
            v = self.compare()
            self.take(")")
            return v
        if kind == "func":
            return self.func(val)
        raise Unsupported(val)

    def args(self):
        out = []
        if self.peek()[1] == ")":
            self.take()
            return out
        while True:
            out.append(self.compare())
            if self.take()[1] == ")":
                return out

    def func(self, name):
        if name not in self.FUNCS:
            raise Unsupported(name)
        if name == "IF":
            a = self.args()
            cond = a[0]
            if isinstance(cond, str):
                raise Unsupported("text condition")
            if cond:
                return a[1] if len(a) > 1 else True
            return a[2] if len(a) > 2 else False
        if name == "IFERROR":
            return self.args()[0]
        a = self.args()
        nums = [x for v in a for x in (v.values() if isinstance(v, _Range) else [v])]
        if name == "SUM":
            return sum(_num(x) for x in nums if not isinstance(x, str))
        if name == "MAX":
            return max([_num(x) for x in nums if not isinstance(x, str)] or [0])
        if name == "MIN":
            return min([_num(x) for x in nums if not isinstance(x, str)] or [0])
        if name == "ABS":
            return abs(_num(a[0]))
        if name == "AND":
            return all(bool(_num(x)) for x in nums)
        if name == "OR":
            return any(bool(_num(x)) for x in nums)
        digits = int(_num(a[1])) if len(a) > 1 else 0
        if name == "ROUND":
            return _round_half_up(_num(a[0]), digits)
        import math
        f = 10 ** digits
        v = _num(a[0]) * f
        return (math.ceil(abs(v)) if name == "ROUNDUP" else math.floor(abs(v))) * (1 if v >= 0 else -1) / f


class _Range:
    def __init__(self, ref, getter):
        a, b = ref.split(":")
        (c1, r1), (c2, r2) = split_ref(a), split_ref(b)
        if (r2 - r1 + 1) * (col_to_num(c2) - col_to_num(c1) + 1) > 5000:
            raise Unsupported("range too large")
        self.cells = [f"{num_to_col(c)}{r}" for r in range(r1, r2 + 1)
                      for c in range(col_to_num(c1), col_to_num(c2) + 1)]
        self.get = getter

    def values(self):
        return [v for v in (self.get(c) for c in self.cells) if v is not None and v != ""]


def _round_half_up(x, digits):
    from decimal import ROUND_HALF_UP, Decimal
    return float(Decimal(repr(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def _num(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, _Range):
        raise Unsupported("range used as value")
    raise Unsupported(f"text {v!r} used as number")


def _text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _eq(a, b):
    if isinstance(a, str) or isinstance(b, str):
        return _text(a).lower() == _text(b).lower()
    return _num(a) == _num(b)


def _cmp_gt(a, b):
    if isinstance(a, str) and isinstance(b, str):   # e.g. B5>"" (non-empty text test)
        return a > b
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str)                   # Excel: text sorts after numbers
    return _num(a) > _num(b)


# --------------------------------------------------------------------------- sheet
class Sheet:
    def __init__(self, book: "Book", name: str, part: str):
        self.book, self.name, self.part = book, name, part
        self.root = etree.fromstring(book.parts[part])
        self.data = self.root.find(q("sheetData"))
        self.rows = {int(r.get("r")): r for r in self.data.findall(q("row"))}
        self.cells = {}
        for r in self.rows.values():
            for c in r.findall(q("c")):
                self.cells[c.get("r")] = c
        self._shared = {}   # si -> (master ref, formula text, ref range)
        for ref, c in self.cells.items():
            f = c.find(q("f"))
            if f is not None and f.get("t") == "shared" and f.text:
                self._shared[f.get("si")] = (ref, f.text, f.get("ref"))
        self.dirty = False

    # ---- reading
    def value(self, ref: str):
        c = self.cells.get(ref)
        if c is None:
            return None
        t = c.get("t")
        if t == "inlineStr":
            return "".join(c.find(q("is")).itertext())
        v = c.find(q("v"))
        if v is None or v.text is None:
            return None
        if t == "s":
            return self.book.shared_strings[int(v.text)]
        if t in ("str", "e"):
            return v.text
        if t == "b":
            return v.text == "1"
        return float(v.text)

    def formula(self, ref: str) -> str | None:
        c = self.cells.get(ref)
        f = c.find(q("f")) if c is not None else None
        if f is None:
            return None
        if f.get("t") == "shared":
            master = self._shared.get(f.get("si"))
            if master is None:
                return None
            mref, text, _ = master
            (mc, mr), (cc, cr) = split_ref(mref), split_ref(ref)
            return translate(text, cr - mr, col_to_num(cc) - col_to_num(mc))
        if f.get("t") == "array":
            return None
        return f.text

    def max_row(self) -> int:
        return max(self.rows) if self.rows else 0

    # ---- writing helpers
    def _row(self, r: int, template: int | None = None):
        row = self.rows.get(r)
        if row is not None:
            return row
        row = etree.Element(q("row"), nsmap=None)
        row.set("r", str(r))
        tmpl = self.rows.get(template) if template else None
        if tmpl is not None:
            for k, v in tmpl.attrib.items():
                if k != "r":
                    row.set(k, v)
        after = [x for x in self.rows if x < r]
        if after:
            self.rows[max(after)].addnext(row)
        else:
            self.data.insert(0, row)
        self.rows[r] = row
        return row

    def _cell(self, ref: str, template_row: int | None = None):
        c = self.cells.get(ref)
        if c is not None:
            return c
        col, r = split_ref(ref)
        row = self._row(r, template_row)
        c = etree.SubElement(row, q("c"))
        c.set("r", ref)
        # keep cells in column order
        cells = sorted(row.findall(q("c")), key=lambda x: col_to_num(split_ref(x.get("r"))[0]))
        for x in cells:
            row.remove(x)
        for x in cells:
            row.append(x)
        if template_row:
            t = self.cells.get(f"{col}{template_row}")
            if t is not None and t.get("s"):
                c.set("s", t.get("s"))
        self.cells[ref] = c
        return c

    def _unshare(self, ref: str):
        """Before changing a cell that others copy their formula from, give them explicit formulas."""
        c = self.cells.get(ref)
        f = c.find(q("f")) if c is not None else None
        if f is None or f.get("t") != "shared" or not f.text:
            return
        si = f.get("si")
        for other_ref, other in self.cells.items():
            of = other.find(q("f"))
            if of is not None and of.get("t") == "shared" and of.get("si") == si and other_ref != ref:
                text = self.formula(other_ref)
                for k in ("t", "si", "ref"):
                    of.attrib.pop(k, None)
                of.text = text
        for k in ("t", "si", "ref"):
            f.attrib.pop(k, None)
        self._shared.pop(si, None)

    def _clear(self, c):
        self._unshare(c.get("r"))
        for child in list(c):
            c.remove(child)
        c.attrib.pop("t", None)
        c.attrib.pop("cm", None)
        c.attrib.pop("vm", None)

    def set(self, ref: str, value, template_row: int | None = None, style_ref: str | None = None):
        """Write a plain value (text, number, date or None to blank the cell)."""
        c = self._cell(ref, template_row)
        if style_ref and self.cells.get(style_ref) is not None and self.cells[style_ref].get("s"):
            c.set("s", self.cells[style_ref].get("s"))
        self._clear(c)
        if value is None or value == "":
            pass
        elif isinstance(value, bool):
            c.set("t", "b")
            etree.SubElement(c, q("v")).text = "1" if value else "0"
        elif isinstance(value, (int, float)):
            etree.SubElement(c, q("v")).text = _fmt_num(value)
        elif isinstance(value, (date, datetime)):
            etree.SubElement(c, q("v")).text = _fmt_num(excel_serial(value))
            if not self.book.is_date_style(c.get("s")):
                s = self._date_style_for(split_ref(ref)[0])
                if s is not None:
                    c.set("s", s)
        else:
            c.set("t", "inlineStr")
            is_ = etree.SubElement(c, q("is"))
            t = etree.SubElement(is_, q("t"))
            t.text = str(value)
            if t.text != t.text.strip():
                t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        self.dirty = True

    def _date_style_for(self, col: str):
        """A date-formatted style: preferably one already used in this column."""
        for ref, c in self.cells.items():
            if split_ref(ref)[0] == col and self.book.is_date_style(c.get("s")):
                return c.get("s")
        return min(self.book._date_styles, key=int) if self.book._date_styles else None

    def set_formula(self, ref: str, formula: str, template_row: int | None = None):
        c = self._cell(ref, template_row)
        self._clear(c)
        f = etree.SubElement(c, q("f"))
        f.text = formula.lstrip("=")
        self.dirty = True

    def recalc_row(self, r: int, passes: int = 6) -> None:
        """Store calculated values for formula cells in row r (those we can evaluate)."""
        refs = [ref for ref in self.cells if split_ref(ref)[1] == r and self.formula(ref)]
        for _ in range(passes):
            changed = False
            for ref in refs:
                try:
                    v = _Eval(self.formula(ref), self.value).run()
                except (Unsupported, IndexError, ValueError, TypeError, OverflowError):
                    continue
                if isinstance(v, _Range):
                    continue
                if self._store_cached(ref, v):
                    changed = True
            if not changed:
                break

    def _store_cached(self, ref, v) -> bool:
        c = self.cells[ref]
        old = self.value(ref)
        vel = c.find(q("v"))
        if vel is None:
            vel = etree.SubElement(c, q("v"))
        if isinstance(v, bool):
            c.set("t", "b")
            vel.text = "1" if v else "0"
        elif isinstance(v, str):
            c.set("t", "str")
            vel.text = v
        else:
            c.attrib.pop("t", None)
            vel.text = _fmt_num(v)
        new = self.value(ref)
        self.dirty = True
        return old != new

    def serialize(self) -> bytes:
        last = self.max_row()
        dim = self.root.find(q("dimension"))
        if dim is not None and ":" in dim.get("ref", ""):
            a, b = dim.get("ref").split(":")
            bc, br = split_ref(b)
            if last > br:
                dim.set("ref", f"{a}:{bc}{last}")
        af = self.root.find(q("autoFilter"))
        if af is not None and ":" in af.get("ref", ""):
            a, b = af.get("ref").split(":")
            bc, br = split_ref(b)
            data_last = self.book.last_data_row.get(self.name)
            if data_last and data_last > br:
                af.set("ref", f"{a}:{bc}{data_last}")
                self.book.filter_ranges[self.name] = af.get("ref")
        return etree.tostring(self.root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _fmt_num(v: float) -> str:
    v = float(v)
    if v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


# --------------------------------------------------------------------------- workbook
class Book:
    def __init__(self, path):
        self.path = str(path)
        with zipfile.ZipFile(self.path) as z:
            self.infos = z.infolist()
            self.parts = {i.filename: z.read(i.filename) for i in self.infos}
        wb = etree.fromstring(self.parts["xl/workbook.xml"])
        rels = etree.fromstring(self.parts["xl/_rels/workbook.xml.rels"])
        targets = {r.get("Id"): r.get("Target") for r in rels}
        self.sheet_parts = {}
        for s in wb.find(q("sheets")):
            target = targets[s.get(f"{{{RNS}}}id")].lstrip("/")
            self.sheet_parts[s.get("name")] = target if target.startswith("xl/") else f"xl/{target}"
        self.shared_strings = []
        if "xl/sharedStrings.xml" in self.parts:
            sst = etree.fromstring(self.parts["xl/sharedStrings.xml"])
            self.shared_strings = ["".join(si.itertext()) for si in sst.findall(q("si"))]
        self._date_styles = self._find_date_styles()
        self._sheets = {}
        self.last_data_row = {}
        self.filter_ranges = {}

    def _find_date_styles(self) -> set:
        if "xl/styles.xml" not in self.parts:
            return set()
        st = etree.fromstring(self.parts["xl/styles.xml"])
        custom = {}
        nf = st.find(q("numFmts"))
        if nf is not None:
            for f in nf:
                code = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", f.get("formatCode", "")).lower()
                custom[int(f.get("numFmtId"))] = bool(re.search(r"[dy]", code)) or "mmm" in code
        out = set()
        xfs = st.find(q("cellXfs"))
        for i, xf in enumerate(xfs if xfs is not None else []):
            fid = int(xf.get("numFmtId", 0))
            if 14 <= fid <= 22 or 45 <= fid <= 47 or custom.get(fid):
                out.add(str(i))
        return out

    def is_date_style(self, s) -> bool:
        return s is not None and str(s) in self._date_styles

    def sheet(self, name: str) -> Sheet:
        if name not in self._sheets:
            if name not in self.sheet_parts:
                raise KeyError(f"Sheet '{name}' not found in the workbook")
            self._sheets[name] = Sheet(self, name, self.sheet_parts[name])
        return self._sheets[name]

    def _patch_workbook(self):
        wb = etree.fromstring(self.parts["xl/workbook.xml"])
        calc = wb.find(q("calcPr"))
        if calc is None:
            calc = etree.SubElement(wb, q("calcPr"))
        calc.set("fullCalcOnLoad", "1")
        # keep the Purchase/Sales filter ranges covering the new rows
        names = wb.find(q("definedNames"))
        sheets = [s.get("name") for s in wb.find(q("sheets"))]
        if names is not None:
            for dn in names:
                if dn.get("name") == "_xlnm._FilterDatabase" and dn.get("localSheetId") is not None:
                    sname = sheets[int(dn.get("localSheetId"))]
                    if sname in self.filter_ranges:
                        a, b = self.filter_ranges[sname].split(":")
                        ca, ra = split_ref(a)
                        cb, rb = split_ref(b)
                        dn.text = f"{_quote(sname)}!${ca}${ra}:${cb}${rb}"
        self.parts["xl/workbook.xml"] = etree.tostring(wb, xml_declaration=True, encoding="UTF-8", standalone=True)
        # calcChain lists formula cells; it goes stale when cells change, and Excel rebuilds it.
        if "xl/calcChain.xml" in self.parts:
            del self.parts["xl/calcChain.xml"]
            rels = etree.fromstring(self.parts["xl/_rels/workbook.xml.rels"])
            for r in list(rels):
                if r.get("Target", "").endswith("calcChain.xml"):
                    rels.remove(r)
            self.parts["xl/_rels/workbook.xml.rels"] = etree.tostring(
                rels, xml_declaration=True, encoding="UTF-8", standalone=True)
            ct = etree.fromstring(self.parts["[Content_Types].xml"])
            for o in list(ct):
                if o.get("PartName") == "/xl/calcChain.xml":
                    ct.remove(o)
            self.parts["[Content_Types].xml"] = etree.tostring(ct, xml_declaration=True, encoding="UTF-8",
                                                              standalone=True)

    def save(self, path=None):
        path = str(path or self.path)
        for s in self._sheets.values():
            if s.dirty:
                self.parts[s.part] = s.serialize()
        self._patch_workbook()
        folder = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=folder)
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                written = set()
                for info in self.infos:
                    if info.filename in self.parts:
                        z.writestr(info, self.parts[info.filename], compress_type=zipfile.ZIP_DEFLATED)
                        written.add(info.filename)
                for name, data in self.parts.items():
                    if name not in written:
                        z.writestr(name, data)
            try:
                if os.path.exists(path):
                    with open(path, "r+b"):
                        pass   # fails on Windows while Excel has the file open
                os.replace(tmp, path)
            except PermissionError as exc:
                raise FileLockedError("The Master Sheet is open in Excel. Close it in Excel and save again.") from exc
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


def _quote(sheet: str) -> str:
    return f"'{sheet}'" if re.search(r"[^A-Za-z0-9_]", sheet) else sheet


def backup(path, folder, keep: int = 30) -> str:
    os.makedirs(folder, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    dest = os.path.join(folder, f"{base}__{datetime.now():%Y-%m-%d_%H%M%S_%f}.xlsx")
    shutil.copy2(path, dest)
    olds = sorted(f for f in os.listdir(folder) if f.startswith(base + "__"))
    for f in olds[:-keep]:
        os.remove(os.path.join(folder, f))
    return dest


def usual_formulas(sheet: Sheet, rows: list[int], columns: list[str]) -> dict:
    """For each column, the formula most of the given rows use (as a row-relative pattern)."""
    out = {}
    for col in columns:
        pats = Counter()
        for r in rows:
            f = sheet.formula(f"{col}{r}")
            pats[relative_pattern(f, r) if f else None] += 1
        if pats:
            pat, n = pats.most_common(1)[0]
            if pat is not None:
                out[col] = pat
    return out
