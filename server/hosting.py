"""Whether the app runs on an internet host and its public address.

PythonAnywhere keeps its disk, so the app keeps its data there as on an office PC (PUBLIC_URL tells it the address).
Koyeb, Render and Hugging Face Spaces wipe their disk on every restart, so there the app keeps everything in an
online database and file store instead."""
from __future__ import annotations

import os

# (the host's name, a variable it always sets, a variable holding the public address without https://)
HOSTS = [
    ("Koyeb", "KOYEB_APP_NAME", "KOYEB_PUBLIC_DOMAIN"),
    ("Render", "RENDER", "RENDER_EXTERNAL_HOSTNAME"),
    ("Hugging Face", "SPACE_ID", "SPACE_HOST"),
]


def host() -> str:
    """The internet host's name, "online" for another one given by PUBLIC_URL, or "" on an ordinary computer."""
    for name, marker, _ in HOSTS:
        if os.environ.get(marker):
            return name
    return "online" if os.environ.get("PUBLIC_URL") else ""


def wipes_disk() -> bool:
    return host() in {name for name, _, _ in HOSTS}


def public_url() -> str:
    if os.environ.get("PUBLIC_URL"):
        return os.environ["PUBLIC_URL"].strip().rstrip("/")
    for _, _, domain in HOSTS:
        if os.environ.get(domain):
            return "https://" + os.environ[domain].strip().split(",")[0]
    return ""


def settings_place() -> str:
    """Where the admin types settings such as DATABASE_URL, in the host's own words."""
    return {"Koyeb": "the Koyeb service's Settings → Environment variables",
            "Render": "the Render service's Environment page",
            "Hugging Face": "the Space's Settings → Variables and secrets"}.get(host(), "the host's settings")
