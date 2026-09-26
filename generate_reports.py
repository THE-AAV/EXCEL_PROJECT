"""Generate the Excel report pack with no clicks.

    python generate_reports.py                 # newest file in input/ -> output/
    python generate_reports.py --input X.xlsx  # a specific file
    python generate_reports.py --watch         # keep running; rebuild whenever input/ changes

Use --watch, or schedule the plain command with Windows Task Scheduler / cron,
to have reports produced automatically.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

from mis_reports import Filters, run_reports

BASE = Path(__file__).resolve().parent


def newest(folder: Path) -> Path | None:
    files = [p for p in folder.glob("*.xls*") if not p.name.startswith("~$")]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def generate(src: Path, out_dir: Path, as_of: date | None) -> Path:
    rs = run_reports(src, Filters(as_of=as_of or date.today()))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"Business_Reports_{datetime.now():%Y-%m-%d_%H%M}.xlsx"
    out.write_bytes(rs.to_excel())
    print(f"[{datetime.now():%H:%M:%S}] {src.name} -> {out}  "
          f"(net profit {rs.pnl['net_profit'].sum():,.0f}, payable {rs.creditors.summary['closing'].sum():,.0f}, "
          f"receivable {rs.debtors.summary['closing'].sum():,.0f}, {len(rs.checks)} data check(s))")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, help="Master Sheet file (default: newest file in input/)")
    ap.add_argument("--input-dir", type=Path, default=BASE / "input")
    ap.add_argument("--output-dir", type=Path, default=BASE / "output")
    ap.add_argument("--as-of", type=date.fromisoformat, help="balance date, YYYY-MM-DD (default: today)")
    ap.add_argument("--watch", action="store_true", help="rebuild reports whenever the input file changes")
    ap.add_argument("--interval", type=int, default=30, help="seconds between checks in --watch mode")
    args = ap.parse_args(argv)

    if not args.watch:
        src = args.input or newest(args.input_dir)
        if src is None or not src.exists():
            print(f"No Master Sheet found. Put the .xlsx file in {args.input_dir}", file=sys.stderr)
            return 1
        generate(src, args.output_dir, args.as_of)
        return 0

    print(f"Watching {args.input or args.input_dir} - press Ctrl+C to stop.")
    last = None
    while True:
        src = args.input or newest(args.input_dir)
        if src is not None and src.exists():
            stamp = (src, src.stat().st_mtime)
            if stamp != last:
                time.sleep(2)  # let the copy / Excel save finish
                try:
                    generate(src, args.output_dir, args.as_of)
                    last = stamp
                except Exception as exc:  # keep watching; the file may still be half-written
                    print(f"Could not read {src.name}: {exc}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
