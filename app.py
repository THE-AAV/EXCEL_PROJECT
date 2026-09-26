"""Business Reports app: enter transactions into the Master Sheet and view reports.

Start it with Start_Reports_App.bat (Windows) or ./start_app.sh (Mac/Linux).
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import streamlit as st

from mis_reports import reports as R
from mis_reports.entries import MasterFile, working_file
from mis_reports.loader import load_master
from mis_reports.pipeline import load_aliases, run_reports
from mis_reports.xlsx_edit import backup
from ui import entries_page, reports_page
from ui.common import CSS

BASE = Path(__file__).resolve().parent
INPUT_DIR = BASE / "input"
OUTPUT_DIR = BASE / "output"

st.set_page_config(page_title="Business Reports", page_icon="📊", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_data(show_spinner="Reading the Master Sheet...")
def cached_load(path: str, mtime_ns: int, size: int):
    return load_master(path)


def file_stamp(path: Path):
    s = path.stat()
    return s.st_mtime_ns, s.st_size


# --------------------------------------------------------------------------- sidebar: working file
st.sidebar.title("📊 Business Reports")
mode = st.sidebar.radio("What do you want to do?", ["📝 Enter transactions", "📊 View reports"],
                        key="mode", label_visibility="collapsed")

path = working_file(INPUT_DIR)
with st.sidebar.expander("📁 Master Sheet file", expanded=path is None):
    if path is not None:
        st.caption(f"Working file: **{path.name}** in `{path.parent}`. You can also open it in Excel - "
                   "changes you save there show up here within a few seconds.")
        st.download_button("⬇️ Download the Master Sheet", path.read_bytes(), file_name=path.name,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           width="stretch")
    upload = st.file_uploader("Use a different Master Sheet (.xlsx)", type=["xlsx", "xlsm"],
                              help="The file is copied into the 'input' folder and becomes the working file. "
                                   "Entries are saved into it.")
    if upload is not None and st.session_state.get("uploaded_id") != upload.file_id:
        INPUT_DIR.mkdir(exist_ok=True)
        dest = INPUT_DIR / Path(upload.name).name
        if dest.exists():
            backup(dest, INPUT_DIR / "backups")
        dest.write_bytes(upload.getvalue())
        st.session_state["uploaded_id"] = upload.file_id
        st.cache_data.clear()
        st.rerun()

if path is None:
    st.title("Welcome 👋")
    st.info("**To begin:** open **📁 Master Sheet file** on the left and upload your Master Sheet, **or** copy it "
            f"into the `input` folder (`{INPUT_DIR}`) and refresh this page.")
    st.stop()

st.sidebar.caption(f"Working file: **{path.name}**  \nLast saved "
                   f"{datetime.fromtimestamp(path.stat().st_mtime):%d-%b-%Y %H:%M:%S}")


@st.fragment(run_every="5s")
def watch_file():
    """Reload the app when the Master Sheet is saved from Excel (or anywhere else)."""
    try:
        stamp = file_stamp(path)
    except FileNotFoundError:
        return
    seen = st.session_state.setdefault("file_stamp", stamp)
    if stamp != seen:
        st.session_state["file_stamp"] = stamp
        st.rerun(scope="app")


with st.sidebar:
    watch_file()

try:
    data = cached_load(str(path), *file_stamp(path))
except PermissionError:
    st.warning("The Master Sheet is being saved by Excel - refreshing in a moment...")
    st.stop()
except Exception as exc:  # show a friendly message instead of a stack trace
    st.error(f"This file could not be read as a Master Sheet: {exc}")
    st.stop()
st.session_state["file_stamp"] = file_stamp(path)

aliases = load_aliases()
master = MasterFile(path, backup_dir=INPUT_DIR / "backups", log_path=INPUT_DIR / "activity_log.csv")

if mode.startswith("📝"):
    entries_page.render(data, master, aliases)
    st.stop()

# --------------------------------------------------------------------------- reports
opts = R.filter_options(data, aliases)
st.sidebar.subheader("Choose what to see")
as_of = st.sidebar.date_input("Balances as on", value=date.today(), format="DD/MM/YYYY",
                              help="Debtor / creditor balances and ageing are worked out on this date.")
whole = st.sidebar.checkbox("P&L for all dates", value=True)
d_from = d_to = None
if not whole and opts["min_date"]:
    rng = st.sidebar.date_input("P&L period", value=(opts["min_date"], opts["max_date"]), format="DD/MM/YYYY")
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        d_from, d_to = rng
products = st.sidebar.multiselect("Products", opts["products"], placeholder="All products")
types = st.sidebar.multiselect("Type", opts["types"], placeholder="All types")
sub_types = st.sidebar.multiselect("Sub Type", opts["sub_types"], placeholder="All sub types")
companies = st.sidebar.multiselect("Company", opts["companies"], placeholder="All companies")

filters = R.Filters(date_from=d_from, date_to=d_to, as_of=as_of, types=types, sub_types=sub_types,
                    companies=companies, products=products, aliases=aliases)
rs = run_reports(None, filters, data=data)
excel_bytes = rs.to_excel()
file_name = f"Business_Reports_{as_of:%d-%m-%Y}.xlsx"

st.sidebar.subheader("Download")
st.sidebar.download_button("⬇️ Download all reports (Excel)", excel_bytes, file_name=file_name,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           type="primary", width="stretch")
if st.sidebar.button("💾 Also save a copy in the output folder", width="stretch"):
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / file_name).write_bytes(excel_bytes)
    st.sidebar.success(f"Saved to output/{file_name}")

reports_page.render(data, rs, opts, aliases, as_of, path.name)
