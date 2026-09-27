"""The web app's backend (FastAPI).

Run for development:   uvicorn server.main:create_app --factory --reload
The built web app in web/dist is served from the same address, so the browser only talks to one server.
"""
from __future__ import annotations

from datetime import date

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from mis_reports import reports as R
from mis_reports.excel_export import build_workbook
from mis_reports.master_sheet import build_master_sheet
from mis_reports.pipeline import load_aliases as csv_aliases

from . import auth, db, imports, store
from .config import BASE, Settings
from .reports_api import ReportCache, report_json, to_json

WEB_DIST = BASE / "web" / "dist"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._@-]+$")
    full_name: str = ""
    role: str
    password: str


class UserPatch(BaseModel):
    full_name: str | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = None
    unlock: bool | None = None


class AliasIn(BaseModel):
    name_in_sheet: str
    report_as: str


def _first_admin_from_settings(engine, settings: Settings) -> None:
    """With ADMIN_PASSWORD set, a brand-new installation starts with that admin instead of the set-up page,
    so nobody else can claim a freshly published site first. Does nothing once any user exists."""
    if not settings.admin_password:
        return
    if len(settings.admin_password) < auth.MIN_PASSWORD:
        raise SystemExit(f"ADMIN_PASSWORD must be at least {auth.MIN_PASSWORD} characters")
    name = settings.admin_username.strip().lower() or "admin"
    with engine.begin() as conn:
        if conn.execute(select(func.count()).select_from(db.users)).scalar_one():
            return
        uid = conn.execute(db.users.insert().values(
            username=name, full_name="", password_hash=auth.hash_password(settings.admin_password), role="admin",
            active=True, created_at=db.utcnow())).inserted_primary_key[0]
        store.audit(conn, {"id": uid, "username": name}, "setup.first_admin")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = db.make_engine(settings.database_url)
    db.init_db(engine, alias_seed=csv_aliases())
    _first_admin_from_settings(engine, settings)
    cache = ReportCache(engine)

    app = FastAPI(title="Business Reports", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings, app.state.engine, app.state.cache = settings, engine, cache

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # Changes must come from our own page: browsers never add this header to a cross-site form post.
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/") \
                and request.headers.get("x-requested-with") != "fetch":
            return JSONResponse({"detail": "Missing request header"}, status.HTTP_403_FORBIDDEN)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    admin, editor, viewer = auth.require("admin"), auth.require("editor"), auth.require("viewer")

    # ------------------------------------------------------------------ sign in
    @app.get("/api/health")
    def health():
        with engine.connect() as conn:
            conn.execute(select(1))
        return {"ok": True}

    @app.get("/api/setup")
    def setup_state():
        with engine.connect() as conn:
            n = conn.execute(select(func.count()).select_from(db.users)).scalar_one()
        return {"needs_first_admin": n == 0}

    @app.post("/api/setup")
    def first_admin(body: UserIn, response: Response):
        """Creates the first admin on a brand-new installation; refused once any user exists."""
        auth.validate_password(body.password)
        with engine.begin() as conn:
            if conn.execute(select(func.count()).select_from(db.users)).scalar_one():
                raise HTTPException(status.HTTP_409_CONFLICT, "Setup is already done. Please sign in.")
            uid = conn.execute(db.users.insert().values(
                username=body.username.strip().lower(), full_name=body.full_name.strip(),
                password_hash=auth.hash_password(body.password), role="admin", active=True,
                created_at=db.utcnow())).inserted_primary_key[0]
            store.audit(conn, {"id": uid, "username": body.username.strip().lower()}, "setup.first_admin")
        return login(LoginIn(username=body.username, password=body.password), response)

    @app.post("/api/auth/login")
    def login(body: LoginIn, response: Response):
        u = auth.login(engine, body.username, body.password, settings)
        with engine.begin() as conn:
            store.audit(conn, {"id": u.id, "username": u.username}, "auth.login")
        response.set_cookie(auth.COOKIE, auth.make_token(u, settings), httponly=True, samesite="strict",
                            secure=settings.secure_cookies, max_age=int(settings.session_hours * 3600), path="/")
        return to_json(auth.public_user(u))

    @app.post("/api/auth/logout")
    def logout(response: Response):
        response.delete_cookie(auth.COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(user=Depends(auth.current_user)):
        return user

    @app.post("/api/auth/password")
    def change_password(body: PasswordIn, response: Response, user=Depends(auth.current_user)):
        auth.validate_password(body.new_password)
        with engine.begin() as conn:
            u = conn.execute(select(db.users).where(db.users.c.id == user["id"])).first()
            if not auth.check_password(body.current_password, u.password_hash):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "The current password is not right")
            conn.execute(update(db.users).where(db.users.c.id == u.id).values(
                password_hash=auth.hash_password(body.new_password), token_version=u.token_version + 1))
            store.audit(conn, user, "auth.password_changed")
            u = conn.execute(select(db.users).where(db.users.c.id == user["id"])).first()
        # other devices are signed out; this one gets a fresh session
        response.set_cookie(auth.COOKIE, auth.make_token(u, settings), httponly=True, samesite="strict",
                            secure=settings.secure_cookies, max_age=int(settings.session_hours * 3600), path="/")
        return {"ok": True}

    # ------------------------------------------------------------------ users (admin)
    @app.get("/api/users")
    def list_users(_=Depends(admin)):
        with engine.connect() as conn:
            return to_json([auth.public_user(u) for u in conn.execute(select(db.users).order_by(db.users.c.username))])

    @app.post("/api/users", status_code=201)
    def add_user(body: UserIn, user=Depends(admin)):
        if body.role not in db.ROLES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Role must be admin, editor or viewer")
        auth.validate_password(body.password)
        name = body.username.strip().lower()
        with engine.begin() as conn:
            if conn.execute(select(db.users.c.id).where(db.users.c.username == name)).first():
                raise HTTPException(status.HTTP_409_CONFLICT, f"User ID '{name}' is already taken")
            uid = conn.execute(db.users.insert().values(
                username=name, full_name=body.full_name.strip(), password_hash=auth.hash_password(body.password),
                role=body.role, active=True, created_at=db.utcnow())).inserted_primary_key[0]
            store.audit(conn, user, "user.add", target=name, role=body.role)
            return to_json(auth.public_user(conn.execute(select(db.users).where(db.users.c.id == uid)).first()))

    @app.patch("/api/users/{user_id}")
    def edit_user(user_id: int, body: UserPatch, user=Depends(admin)):
        with engine.begin() as conn:
            u = conn.execute(select(db.users).where(db.users.c.id == user_id)).first()
            if u is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
            values, changes = {}, {}
            if body.full_name is not None:
                values["full_name"] = changes["full_name"] = body.full_name.strip()
            if body.role is not None and body.role != u.role:
                if body.role not in db.ROLES:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Role must be admin, editor or viewer")
                values["role"] = changes["role"] = body.role
            if body.active is not None and body.active != u.active:
                values["active"] = changes["active"] = body.active
            if body.password:
                auth.validate_password(body.password)
                values["password_hash"] = auth.hash_password(body.password)
                changes["password"] = "reset"
            if body.unlock:
                values.update(failed_logins=0, locked_until=None)
                changes["unlocked"] = True
            if ("role" in values and values["role"] != "admin") or values.get("active") is False:
                if u.role == "admin" and u.active:
                    admins = conn.execute(select(func.count()).select_from(db.users).where(
                        db.users.c.role == "admin", db.users.c.active.is_(True))).scalar_one()
                    if admins <= 1:
                        raise HTTPException(status.HTTP_409_CONFLICT, "There must always be at least one admin")
            if "role" in values or "active" in values or "password_hash" in values:
                values["token_version"] = u.token_version + 1  # sign them out so the change applies now
            if values:
                conn.execute(update(db.users).where(db.users.c.id == user_id).values(**values))
                store.audit(conn, user, "user.edit", target=u.username, **changes)
            return to_json(auth.public_user(conn.execute(select(db.users).where(db.users.c.id == user_id)).first()))

    # ------------------------------------------------------------------ imports (admin)
    @app.get("/api/imports")
    def list_imports(_=Depends(admin)):
        with engine.connect() as conn:
            return to_json(imports.list_batches(conn))

    @app.post("/api/imports", status_code=201)
    async def upload(file: UploadFile = File(...), user=Depends(admin)):
        content = await file.read(imports.MAX_UPLOAD_MB * 1024 * 1024 + 1)
        return to_json(imports.create_preview(engine, settings, user, file.filename, content))

    @app.post("/api/imports/{batch_id}/confirm")
    def confirm_import(batch_id: int, user=Depends(admin)):
        imports.confirm(engine, settings, user, batch_id)
        cache.clear()
        with engine.connect() as conn:
            return to_json(imports.batch_row(conn, batch_id))

    @app.post("/api/imports/{batch_id}/discard")
    def discard_import(batch_id: int, user=Depends(admin)):
        imports.discard(engine, settings, user, batch_id)
        return {"ok": True}

    @app.post("/api/imports/{batch_id}/restore")
    def restore_import(batch_id: int, user=Depends(admin)):
        imports.restore(engine, settings, user, batch_id)
        cache.clear()
        with engine.connect() as conn:
            return to_json(imports.batch_row(conn, batch_id))

    @app.get("/api/imports/{batch_id}/file")
    def import_file(batch_id: int, _=Depends(admin)):
        with engine.connect() as conn:
            b = imports._get(conn, batch_id)
            content = imports.file_content(conn, settings, b)
        if content is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is no longer kept")
        return Response(content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{b.filename}"'})

    # ------------------------------------------------------------------ reports (everyone signed in)
    def filters(as_of: date | None = None, date_from: date | None = None, date_to: date | None = None,
                products: list[str] = Query(default=[]), types: list[str] = Query(default=[]),
                sub_types: list[str] = Query(default=[]), companies: list[str] = Query(default=[])) -> R.Filters:
        return R.Filters(date_from=date_from, date_to=date_to, as_of=as_of or date.today(), types=types,
                         sub_types=sub_types, companies=companies, products=products)

    @app.get("/api/status")
    def data_status(_=Depends(viewer)):
        _, data, aliases = cache.data()
        with engine.connect() as conn:
            active = conn.execute(select(db.import_batches).where(db.import_batches.c.status == "active")).first()
        return to_json({
            "has_data": active is not None,
            "source": {"filename": active.filename, "loaded_at": active.confirmed_at} if active else None,
            "options": R.filter_options(data, aliases),
        })

    @app.get("/api/reports")
    def reports(f: R.Filters = Depends(filters), _=Depends(viewer)):
        return report_json(cache.reports(f))

    @app.get("/api/reports/excel")
    def reports_excel(f: R.Filters = Depends(filters), user=Depends(viewer)):
        rs = cache.reports(f)
        name = f"Business_Reports_{f.as_of:%Y-%m-%d}.xlsx"
        with engine.begin() as conn:
            store.audit(conn, user, "reports.download")
        return Response(build_workbook(rs), headers={"Content-Disposition": f'attachment; filename="{name}"'},
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get("/api/master-sheet")
    def master_sheet(user=Depends(viewer)):
        """The Master Sheet workbook (Purchase, Sales, PO, SO, Total Debtor Creditor, masters, Display),
        rebuilt from the saved data with the sheet's own formulas."""
        _, data, _ = cache.data()
        name = f"Master Sheet {db.utcnow():%Y-%m-%d}.xlsx"
        with engine.begin() as conn:
            store.audit(conn, user, "master_sheet.download")
        return Response(build_master_sheet(data), media_type=XLSX,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ------------------------------------------------------------------ product names
    @app.get("/api/aliases")
    def get_aliases(_=Depends(viewer)):
        with engine.connect() as conn:
            return [{"name_in_sheet": k, "report_as": v} for k, v in sorted(store.load_aliases(conn).items())]

    @app.put("/api/aliases")
    def put_aliases(body: list[AliasIn], user=Depends(admin)):
        rows = {a.name_in_sheet.strip(): a.report_as.strip() for a in body
                if a.name_in_sheet.strip() and a.report_as.strip()}
        with engine.begin() as conn:
            conn.execute(delete(db.product_aliases))
            if rows:
                conn.execute(db.product_aliases.insert(),
                             [{"name_in_sheet": k, "report_as": v} for k, v in rows.items()])
            store.audit(conn, user, "aliases.save", count=len(rows))
        cache.clear()
        return get_aliases()

    # ------------------------------------------------------------------ audit log (admin)
    @app.get("/api/audit")
    def audit_log(limit: int = Query(200, le=1000), _=Depends(admin)):
        with engine.connect() as conn:
            rows = conn.execute(select(db.audit_log).order_by(db.audit_log.c.id.desc()).limit(limit))
            return to_json([{"id": r.id, "at": r.at, "username": r.username, "action": r.action,
                             "details": r.details} for r in rows])

    # ------------------------------------------------------------------ the web app
    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            target = (WEB_DIST / path).resolve()
            if path and target.is_file() and WEB_DIST.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(WEB_DIST / "index.html")

    return app
