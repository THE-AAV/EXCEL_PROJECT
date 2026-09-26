"""'View sheets' page: look at any workbook the way Excel shows it, with a tab for every sheet."""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from . import records_view
from .records_view import load_tables
from .sheet_viewer import (column_values, date_number, default_header_row, filter_rows, header_labels,
                           is_date_column, is_numeric_column, load_workbook_views, render_html)

PAGE_ROWS = 1000
GRID_HEIGHT = 620


@st.cache_resource(show_spinner="Opening the workbook...", max_entries=8)
def _views_from_path(path: str, mtime_ns: int, indian: bool):
    return load_workbook_views(path, indian)


@st.cache_resource(show_spinner="Opening the workbook...", max_entries=4)
def _views_from_bytes(content: bytes, indian: bool):
    return load_workbook_views(content, indian)


def _files(working: Path | None, input_dir: Path, output_dir: Path) -> dict[str, Path]:
    out = {}
    if working:
        out[f"📘 {working.name}  (working Master Sheet)"] = working
    for p in sorted(input_dir.glob("*.xls*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if p != working and not p.name.startswith("~$"):
            out[f"📗 {p.name}  (input folder)"] = p
    for p in sorted(output_dir.glob("*.xls*"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        if not p.name.startswith("~$"):
            out[f"📊 {p.name}  (saved report)"] = p
    return out


def render(working: Path | None, input_dir: Path, output_dir: Path):
    st.title("View Sheets")
    st.markdown("<span class='hint'>All the entries in every sheet, laid out cleanly with filters. The page "
                "refreshes by itself when the file changes - from this app or from Excel.</span>",
                unsafe_allow_html=True)

    files = _files(working, input_dir, output_dir)
    uploads = st.session_state.setdefault("viewer_uploads", {})
    for name in uploads:
        files[f"📎 {name}  (opened here, view only)"] = name

    top = st.columns([4, 2])
    with top[1]:
        up = st.file_uploader("Open another Excel file", type=["xlsx", "xlsm"], key="viewer_upload",
                              help="Only shown here - the file is not changed or saved anywhere.")
        if up is not None and up.name not in uploads:
            uploads[up.name] = up.getvalue()
            st.session_state["viewer_file"] = f"📎 {up.name}  (opened here, view only)"
            st.rerun()
    if not files:
        st.info("No workbook yet. Put a file in the `input` folder or open one with the box on the right.")
        return
    labels = list(files)
    if st.session_state.get("viewer_file") not in labels:
        st.session_state["viewer_file"] = labels[0]
    with top[0]:
        choice = st.selectbox("Workbook", labels, key="viewer_file")
    source = files[choice]
    layout = st.segmented_control("Show as", ["🧾 Clean table of entries", "📄 Excel layout"], key="viewer_layout",
                                  default="🧾 Clean table of entries")
    if layout != "📄 Excel layout":
        _clean(source, choice, working, uploads)
        return

    opts = st.columns([3, 1.4, 1.4, 1.6])
    find = opts[0].text_input("🔍 Find", key="viewer_find", placeholder="Type to show only matching rows")
    show_formulas = opts[1].toggle("Show formulas", key="viewer_formulas")
    zoom = opts[2].select_slider("Zoom", [50, 67, 75, 85, 100, 115, 125, 150], value=100, key="viewer_zoom")
    digits = opts[3].radio("Numbers", ["12,34,567", "1,234,567"], horizontal=True, key="viewer_digits",
                           help="Indian or international digit grouping")
    indian = digits == "12,34,567"

    try:
        if isinstance(source, Path):
            stat = source.stat()
            views = _views_from_path(str(source), stat.st_mtime_ns, indian)
            st.session_state["watch_extra"] = [str(source)] if source != working else []
            saved = f"Last saved {datetime.fromtimestamp(stat.st_mtime):%d-%b-%Y %H:%M:%S}"
            content = None
        else:
            content = uploads[source]
            views = _views_from_bytes(content, indian)
            st.session_state["watch_extra"] = []
            saved = "Opened here (view only)"
    except PermissionError:
        st.warning("The file is being saved by Excel - refreshing in a moment...")
        return
    except Exception as exc:
        st.error(f"This file could not be opened: {exc}")
        return
    if not views:
        st.info("This workbook has no sheets to show.")
        return

    names = [v["name"] + (" (hidden)" if v["state"] == "hidden" else "") for v in views]
    wb_key = hashlib.md5(choice.encode()).hexdigest()[:8]
    sheet_key = f"viewer_sheet_{wb_key}"
    if st.session_state.get(sheet_key) not in names:   # first visit, or the tab was clicked off
        last = st.session_state.get(sheet_key + "_last")
        opening = next((n for n, v in zip(names, views) if v["active"] and v["rows"]), None) \
            or next((n for n, v in zip(names, views) if v["rows"]), names[0])
        st.session_state[sheet_key] = last if last in names else opening
    st.session_state[sheet_key + "_last"] = st.session_state[sheet_key]
    view = views[names.index(st.session_state[sheet_key])]

    filters, sort, header_row = _filter_panel(view, f"vf_{wb_key}_{view['name']}")
    shown = filter_rows(view, header_row, filters, sort) if (filters or sort) else None

    row_from, row_to = 1, None
    if view["rows"] > PAGE_ROWS and not find and shown is None:
        pages = [(i, min(i + PAGE_ROWS - 1, view["rows"])) for i in range(1, view["rows"] + 1, PAGE_ROWS)]
        pick = st.selectbox("Rows", [f"{a:,} - {b:,}" for a, b in pages], key=f"viewer_page_{wb_key}_{view['name']}")
        row_from, row_to = pages[[f"{a:,} - {b:,}" for a, b in pages].index(pick)]

    if view["rows"] == 0:
        st.info(f"Sheet '{view['name']}' is empty.")
    else:
        page, hits = render_html(view, find=find, show_formulas=show_formulas, zoom=zoom,
                                 row_from=row_from, row_to=row_to, height=GRID_HEIGHT, header_row=header_row,
                                 shown_rows=shown, filter_cols=set(filters))
        components.html(page, height=GRID_HEIGHT + 6, scrolling=False)
        if shown is not None:
            total = len([r for r in range(header_row + 1, view["rows"] + 1) if r not in view["hidden_rows"]])
            st.caption(f"Showing {len(shown):,} of {total:,} rows" + (" (sorted)" if sort else "") +
                       ". Row numbers are the sheet's own.")
        if find:
            st.caption(f"{hits} matching cell(s) for “{find}”. Header rows are always shown.")

    # sheet tabs, like the bottom of an Excel window
    st.segmented_control("Sheets", names, key=sheet_key, label_visibility="collapsed")
    info = [f"**{view['name']}**", f"{view['rows']:,} rows × {view['cols']} columns", saved]
    if any(c["p"] for c in view["cells"].values()):
        info.append("cells with … are worked out when the file is next opened in Excel")
    st.caption(" · ".join(info))
    data = content if content is not None else source.read_bytes()
    st.download_button("⬇️ Download this workbook", data,
                       file_name=source.name if isinstance(source, Path) else source,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@st.cache_resource(show_spinner="Reading the entries...", max_entries=8)
def _tables_from_path(path: str, mtime_ns: int):
    return load_tables(path)


@st.cache_resource(show_spinner="Reading the entries...", max_entries=4)
def _tables_from_bytes(content: bytes):
    return load_tables(content)


def _clean(source, choice: str, working: Path | None, uploads: dict):
    try:
        if isinstance(source, Path):
            stat = source.stat()
            tables = _tables_from_path(str(source), stat.st_mtime_ns)
            st.session_state["watch_extra"] = [str(source)] if source != working else []
            saved = f"Last saved {datetime.fromtimestamp(stat.st_mtime):%d-%b-%Y %H:%M:%S}"
        else:
            tables = _tables_from_bytes(uploads[source])
            st.session_state["watch_extra"] = []
            saved = "Opened here (view only)"
    except PermissionError:
        st.warning("The file is being saved by Excel - refreshing in a moment...")
        return
    except Exception as exc:
        st.error(f"This file could not be opened: {exc}")
        return
    names = [n for n, df in tables.items() if len(df)]
    if not names:
        st.info("This workbook has no entries to show.")
        return
    wb_key = hashlib.md5(choice.encode()).hexdigest()[:8]
    key = f"clean_sheet_{wb_key}"
    preferred = next((n for n in ("Purchase", "Sales") if n in names), names[0])
    if st.session_state.get(key) not in names:
        last = st.session_state.get(key + "_last")
        st.session_state[key] = last if last in names else preferred
    st.session_state[key + "_last"] = st.session_state[key]
    st.segmented_control("Sheet", names, key=key,
                         format_func=lambda n: f"{n}  ({len(tables[n]):,})")
    sheet = st.session_state[key]
    with st.container(border=True):
        st.subheader(sheet)
        records_view.render(tables[sheet], f"rv_{wb_key}_{sheet}", sheet)
    st.caption(saved)


def _filter_panel(view: dict, key: str):
    """Excel-style AutoFilter: pick columns, tick the values to show, text / range conditions, sort."""
    cols_key = f"{key}_cols"
    active = st.session_state.setdefault(cols_key, [])
    title = "⏷ Filter & sort" + (f" - {len(active)} filter(s) on" if active else "")
    filters, sort = {}, None
    with st.expander(title, expanded=bool(active) or bool(st.session_state.get(f"{key}_sortcol"))):
        c = st.columns([1.2, 4, 1.4])
        header_row = int(c[0].number_input("Header row", min_value=1, max_value=max(view["rows"], 1),
                                           value=min(default_header_row(view), max(view["rows"], 1)),
                                           key=f"{key}_hdr", help="The row with the column titles."))
        labels = header_labels(view, header_row)
        choices = [c for c in labels if c not in active]
        with c[1]:
            add = st.selectbox("Add a filter on column", choices, index=None, format_func=labels.get,
                               key=f"{key}_add_{len(active)}", placeholder="Choose a column to filter")
        if add is not None:
            active.append(add)
            st.rerun()
        if active and c[2].button("✖ Clear all filters", key=f"{key}_clear", width="stretch"):
            for col in active:
                for part in ("vals", "text", "min", "max"):
                    st.session_state.pop(f"{key}_{col}_{part}", None)
            active.clear()
            st.rerun()

        for col in list(active):
            if col not in labels:
                active.remove(col)
                continue
            with st.container(border=True):
                h = st.columns([5, 1])
                h[0].markdown(f"**{labels[col]}**")
                if h[1].button("Remove", key=f"{key}_{col}_rm"):
                    active.remove(col)
                    st.rerun()
                values = column_values(view, header_row, col)
                f = {}
                row = st.columns([4, 2, 2])
                f["values"] = row[0].multiselect(
                    f"Show only these values ({len(values):,} different)", values, key=f"{key}_{col}_vals",
                    placeholder="All values - pick the ones to keep")
                if is_date_column(view, header_row, col):
                    lo = row[1].date_input("From date", None, key=f"{key}_{col}_min", format="DD/MM/YYYY")
                    hi = row[2].date_input("To date", None, key=f"{key}_{col}_max", format="DD/MM/YYYY")
                    f["min"] = date_number(lo) if lo else None
                    f["max"] = date_number(hi) + 0.99999 if hi else None
                elif is_numeric_column(view, header_row, col):
                    lo = row[1].number_input("Min", value=None, key=f"{key}_{col}_min")
                    hi = row[2].number_input("Max", value=None, key=f"{key}_{col}_max")
                    f["min"], f["max"] = lo, hi
                else:
                    f["text"] = row[1].text_input("Text contains", key=f"{key}_{col}_text")
                if f.get("values") or f.get("text") or f.get("min") is not None or f.get("max") is not None:
                    filters[col] = f
        s = st.columns([4, 2])
        with s[0]:
            sort_col = st.selectbox("Sort by", list(labels), index=None, format_func=labels.get,
                                    key=f"{key}_sortcol", placeholder="Keep the sheet's order")
        order = s[1].radio("Order", ["A → Z / smallest first", "Z → A / largest first"], key=f"{key}_order",
                           label_visibility="hidden")
        if sort_col is not None:
            sort = (sort_col, order.startswith("A"))
    return filters, sort, header_row
