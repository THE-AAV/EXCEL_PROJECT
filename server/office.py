"""Run the web app on one office computer for everyone on the office network (free, no hosting service).

    python -m server.office            (Start_Web_App.bat does this for you)

It listens on every network card, so other computers and phones on the same Wi-Fi / network open the address it
prints. The data is kept in data/business.db on this computer, copied to data/backups once a day, and the current
Master Sheet is kept up to date in "data/Master Sheet (live).xlsx".
"""
from __future__ import annotations

import os
import shutil
import socket
import threading
import webbrowser
from datetime import date
from pathlib import Path

KEEP_BACKUPS = 30


def lan_addresses() -> list[str]:
    """This computer's addresses on the office network (not the 127.0.0.1 one only it can use)."""
    found = []
    try:  # the address used to reach other machines; nothing is sent
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    return [a for a in dict.fromkeys(found) if not a.startswith("127.")]


def office_urls(port: int) -> list[str]:
    return [f"http://{a}:{port}" for a in lan_addresses()] + [f"http://{socket.gethostname()}:{port}"]


def daily_backup(db_file: Path) -> Path | None:
    """One copy of the database per day in data/backups (the latest 30 are kept)."""
    if not db_file.exists():
        return None
    folder = db_file.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{db_file.stem}-{date.today():%Y-%m-%d}{db_file.suffix}"
    if not target.exists():
        shutil.copy2(db_file, target)
    for old in sorted(folder.glob(f"{db_file.stem}-*{db_file.suffix}"))[:-KEEP_BACKUPS]:
        old.unlink()
    return target


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    from .config import Settings
    settings = Settings()
    if settings.database_url.startswith("sqlite:///"):
        daily_backup(Path(settings.database_url[len("sqlite:///"):]))

    line = "=" * 64
    print(f"\n{line}\n  Business Reports is running on this computer.\n")
    print(f"  On this computer open:   http://localhost:{port}")
    print("  Others in the office open one of these in their browser:")
    for url in office_urls(port):
        print(f"      {url}")
    print(f"\n  Keep this window open while people use the app. Close it to stop.")
    print(f"  Data and backups: {settings.data_dir}")
    print(f"{line}\n")
    threading.Timer(2.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    uvicorn.run("server.main:create_app", factory=True, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
