"""Settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from . import hosting

BASE = Path(__file__).resolve().parent.parent


def _secret(data_dir: Path, database_url: str) -> str:
    """SECRET_KEY from the environment, or one generated once and kept in the data folder. With an online
    database the app keeps it there instead (see main.create_app), because free hosts wipe their disk."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    if not database_url.startswith("sqlite"):
        return ""
    path = data_dir / "secret_key"
    if not path.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(48))
        path.chmod(0o600)
    return path.read_text().strip()


def normalize_database_url(url: str) -> str:
    """Hosting services hand out postgres://... addresses; SQLAlchemy needs to be told to use psycopg."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", BASE / "data")))
    database_url: str = ""
    secret_key: str = ""
    session_hours: float = float(os.environ.get("SESSION_HOURS", "12"))
    max_failed_logins: int = int(os.environ.get("MAX_FAILED_LOGINS", "5"))
    lockout_minutes: int = int(os.environ.get("LOCKOUT_MINUTES", "15"))
    # on for internet hosts (they use https), off for the office network (plain http)
    secure_cookies: bool = field(default_factory=lambda: os.environ.get(
        "SECURE_COOKIES", "1" if hosting.host() else "0") == "1")
    # optional: creates this admin on a brand-new installation instead of the set-up page
    admin_username: str = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password: str = os.environ.get("ADMIN_PASSWORD", "")

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        # PostgreSQL in production (DATABASE_URL=postgresql+psycopg://...); a local SQLite file otherwise
        self.database_url = self.database_url or os.environ.get("DATABASE_URL") or \
            f"sqlite:///{self.data_dir / 'business.db'}"
        self.database_url = normalize_database_url(self.database_url)
        self.secret_key = self.secret_key or _secret(self.data_dir, self.database_url)

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"
