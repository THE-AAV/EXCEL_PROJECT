"""Settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def _secret(data_dir: Path) -> str:
    """SECRET_KEY from the environment, or one generated once and kept in the data folder."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = data_dir / "secret_key"
    if not path.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(48))
        path.chmod(0o600)
    return path.read_text().strip()


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", BASE / "data")))
    database_url: str = ""
    secret_key: str = ""
    session_hours: float = float(os.environ.get("SESSION_HOURS", "12"))
    max_failed_logins: int = int(os.environ.get("MAX_FAILED_LOGINS", "5"))
    lockout_minutes: int = int(os.environ.get("LOCKOUT_MINUTES", "15"))
    secure_cookies: bool = os.environ.get("SECURE_COOKIES", "0") == "1"

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        # PostgreSQL in production (DATABASE_URL=postgresql+psycopg://...); a local SQLite file otherwise
        self.database_url = self.database_url or os.environ.get("DATABASE_URL") or \
            f"sqlite:///{self.data_dir / 'business.db'}"
        self.secret_key = self.secret_key or _secret(self.data_dir)

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"
