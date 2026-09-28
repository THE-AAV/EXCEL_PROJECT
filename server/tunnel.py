"""A free internet link to the app on this computer, through a Cloudflare Quick Tunnel (no account, no card).

cloudflared connects out to Cloudflare, which hands back a random https://....trycloudflare.com address that
reaches this computer from anywhere. The address changes each time the app starts; the Users page shows the
current one. Nothing has to be opened in the router or firewall.
"""
from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("tunnel")
LINK = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
RELEASES = "https://github.com/cloudflare/cloudflared/releases/latest/download/"

state = {"url": "", "problem": ""}


def _download_name() -> str | None:
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    if sys.platform == "win32":
        return f"cloudflared-windows-{arch}.exe"
    if sys.platform.startswith("linux"):
        return f"cloudflared-linux-{arch}"
    return None   # macOS: brew install cloudflared


def find_cloudflared(data_dir: Path) -> Path | None:
    """cloudflared next to the app, in the data folder, on the PATH, or downloaded once into the data folder."""
    exe = "cloudflared.exe" if sys.platform == "win32" else "cloudflared"
    for p in (Path(sys.executable).parent / exe, Path(__file__).resolve().parent.parent / exe, data_dir / exe):
        if p.is_file():
            return p
    if shutil.which("cloudflared"):
        return Path(shutil.which("cloudflared"))
    name = _download_name()
    if not name:
        return None
    target = data_dir / exe
    print("  Downloading the free internet-link program (once, about 40 MB)...")
    data_dir.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".part")
    urllib.request.urlretrieve(RELEASES + name, part)
    part.replace(target)
    target.chmod(0o755)
    return target


def _run(cmd: list[str], on_link) -> None:
    """Keeps the tunnel up: starts cloudflared again if it stops (for example after the internet drops)."""
    wait = 5
    while True:
        started = time.monotonic()
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            state["problem"] = f"the internet link could not start ({e})"
            return
        for line in proc.stdout:
            m = LINK.search(line)
            if m and m.group(0) != state["url"]:
                state["url"], state["problem"] = m.group(0), ""
                on_link(state["url"])
        proc.wait()
        state["url"] = ""
        state["problem"] = "the internet link dropped; trying again"
        wait = 5 if time.monotonic() - started > 60 else min(wait * 2, 300)
        time.sleep(wait)


def start(port: int, data_dir: Path, on_link=lambda url: None) -> bool:
    """Starts the link in the background. False (with state["problem"] set) when it can't be started."""
    if os.environ.get("INTERNET_LINK", "1") == "0":
        state["problem"] = "switched off (INTERNET_LINK=0)"
        return False
    try:
        exe = find_cloudflared(data_dir)
    except Exception as e:   # no internet, blocked download...
        exe, state["problem"] = None, f"the internet-link program could not be downloaded ({e})"
    if not exe:
        state["problem"] = state["problem"] or "the internet-link program (cloudflared) is missing"
        return False
    cmd = [str(exe), "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"]
    threading.Thread(target=_run, args=(cmd, on_link), daemon=True, name="internet-link").start()
    return True
