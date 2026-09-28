"""Passwords, sign-in sessions and role checks.

Passwords are stored as bcrypt hashes. A signed-in user gets a signed token in an httpOnly cookie, so page
scripts cannot read it. Roles are checked on every API call, not just by hiding buttons:
  admin  - everything, including users, imports and product names
  editor - enter and change transactions (from Phase 2), see all reports
  viewer - read-only: reports, dashboard, downloads
"""
from __future__ import annotations

from datetime import timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select, update

from . import db

COOKIE = "session"
RANK = {"viewer": 0, "editor": 1, "admin": 2}
MIN_PASSWORD = 8
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Password must be at least {MIN_PASSWORD} characters")


def make_token(user, settings) -> str:
    now = db.utcnow()
    return jwt.encode({"sub": str(user.id), "ver": user.token_version, "iat": now,
                       "exp": now + timedelta(hours=settings.session_hours)},
                      settings.secret_key, algorithm="HS256")


def public_user(u) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role, "active": u.active,
            "created_at": u.created_at, "last_login": u.last_login, "can_files": bool(u.can_files),
            "locked": bool(u.locked_until and u.locked_until > db.utcnow())}


def login(engine, username: str, password: str, settings):
    """Returns the user row, or raises 401 / 423. Wrong passwords count towards a temporary lock
    (saved in their own transaction, so raising the error does not roll the count back)."""
    with engine.begin() as conn:
        u = conn.execute(select(db.users).where(db.users.c.username == username.strip().lower())).first()
    fail = HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong user ID or password")
    if u is None:
        check_password(password, _DUMMY_HASH)  # take as long as a real check
        raise fail
    now = db.utcnow()
    if u.locked_until and u.locked_until > now:
        mins = max(1, int((u.locked_until - now).total_seconds() // 60) + 1)
        raise HTTPException(status.HTTP_423_LOCKED, f"Too many wrong passwords. Try again in {mins} minute(s).")
    if not check_password(password, u.password_hash):
        failed = u.failed_logins + 1
        values = {"failed_logins": failed}
        if failed >= settings.max_failed_logins:
            values = {"failed_logins": 0, "locked_until": now + timedelta(minutes=settings.lockout_minutes)}
        with engine.begin() as conn:
            conn.execute(update(db.users).where(db.users.c.id == u.id).values(**values))
        raise fail
    if not u.active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This user has been switched off. Ask an admin.")
    with engine.begin() as conn:
        conn.execute(update(db.users).where(db.users.c.id == u.id)
                     .values(failed_logins=0, locked_until=None, last_login=now))
        return conn.execute(select(db.users).where(db.users.c.id == u.id)).first()


def current_user(request: Request):
    """FastAPI dependency: the signed-in user as a dict, or 401."""
    app = request.app
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in")
    try:
        claims = jwt.decode(token, app.state.settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has ended. Please sign in again.")
    with app.state.engine.connect() as conn:
        u = conn.execute(select(db.users).where(db.users.c.id == int(claims["sub"]))).first()
    if u is None or not u.active or u.token_version != claims.get("ver"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has ended. Please sign in again.")
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
            "can_files": u.role == "admin" or bool(u.can_files)}


def require(role: str):
    """Dependency factory: the signed-in user must have `role` or a higher one."""
    def check(user=Depends(current_user)):
        if RANK[user["role"]] < RANK[role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role does not allow this")
        return user
    return check
