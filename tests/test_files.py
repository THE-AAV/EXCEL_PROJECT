"""The Files section: folders, uploads in pieces, versions, sheets, delete / restore, who may change files."""
import io

import openpyxl
import pytest

from server import files as F
from tests.test_server import add_user, client, rich_master, settings, setup_admin, sign_in  # noqa: F401


def workbook(*sheets) -> bytes:
    wb = openpyxl.Workbook()
    wb.active.title = sheets[0]
    for name in sheets[1:]:
        wb.create_sheet(name)
    for ws in wb.worksheets:
        ws.append(["Party", "Amount"])
        for i in range(3):
            ws.append([f"P{i}", i * 10])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def upload(client, name, content, folder_id=None, file_id=None, piece=None):
    r = client.post("/api/files/uploads", json={"name": name, "size": len(content), "folder_id": folder_id,
                                                "file_id": file_id})
    assert r.status_code == 201, r.text
    up = r.json()
    step = piece or up["chunk_size"]
    for off in range(0, max(len(content), 1), step):
        r = client.put(f"/api/files/uploads/{up['upload_id']}", params={"offset": off}, content=content[off:off + step])
        assert r.status_code == 200, r.text
    r = client.post(f"/api/files/uploads/{up['upload_id']}/finish")
    assert r.status_code == 200, r.text
    return r.json()


def tree(client):
    return client.get("/api/files").json()


def test_folders_uploads_versions_and_sheets(client, settings):
    setup_admin(client)
    folder = client.post("/api/files/folders", json={"name": "2026 Accounts"}).json()["id"]
    sub = client.post("/api/files/folders", json={"name": "September", "parent_id": folder}).json()["id"]
    assert client.post("/api/files/folders", json={"name": "september", "parent_id": folder}).status_code == 409

    content = workbook("Purchase", "Sales")
    r = upload(client, "Ledger.xlsx", content, sub, piece=1000)   # sent in many small pieces
    assert r["new"] and r["version"] == 1
    t = tree(client)
    f = next(x for x in t["files"] if x["name"] == "Ledger.xlsx")
    assert f["folder_id"] == sub and f["size"] == len(content) and f["changed_by"] == "owner"
    assert f["sheets"] == [{"name": "Purchase", "rows": 4, "cols": 2}, {"name": "Sales", "rows": 4, "cols": 2}]
    assert t["where"] == "on the computer running the app" and t["master"] is None

    # the same name in the same folder is a new version, the old one is kept
    r2 = upload(client, "ledger.xlsx", workbook("Only"), sub)
    assert (r2["file_id"], r2["version"], r2["new"]) == (r["file_id"], 2, False)
    vs = client.get(f"/api/files/{r['file_id']}/versions").json()
    assert [(v["number"], v["by"]) for v in vs] == [(2, "owner"), (1, "owner")]
    old = client.get(f"/api/files/versions/{vs[1]['id']}/download")
    assert old.content == content and "version%201" in old.headers["content-disposition"]

    prev = client.get(f"/api/files/versions/{vs[1]['id']}/sheet", params={"name": "Sales"}).json()
    assert [c[1] for c in prev["cols"]] == ["A", "B"] and prev["rows"][1] == {"_n": 2, "c0": "P0", "c1": 0}

    # rename, move, delete, restore, and it is all in the file's history
    fid = r["file_id"]
    assert client.patch(f"/api/files/{fid}", json={"name": "Ledger 2026.xlsx"}).status_code == 200
    assert client.patch(f"/api/files/{fid}", json={"folder_id": None, "move": True}).status_code == 200
    assert client.delete(f"/api/files/folders/{sub}").status_code == 200        # empty now
    assert client.delete(f"/api/files/folders/{folder}").status_code == 200
    assert client.delete(f"/api/files/{fid}").status_code == 200
    assert tree(client)["files"][0]["deleted_at"]
    assert client.post(f"/api/files/{fid}/restore").status_code == 200
    acts = [a["action"] for a in client.get(f"/api/files/{fid}/activity").json()]
    assert acts == ["file.restore", "file.delete", "file.edit", "file.edit", "file.download", "file.version", "file.upload"]


def test_a_folder_with_files_is_not_deleted_and_moves_cannot_loop(client):
    setup_admin(client)
    a = client.post("/api/files/folders", json={"name": "A"}).json()["id"]
    b = client.post("/api/files/folders", json={"name": "B", "parent_id": a}).json()["id"]
    assert client.patch(f"/api/files/folders/{a}", json={"parent_id": b, "move": True}).status_code == 409
    upload(client, "notes.txt", b"hello", b)
    assert client.delete(f"/api/files/folders/{b}").status_code == 409


def test_only_people_allowed_can_change_files(client):
    setup_admin(client)
    upload(client, "Rates.xlsx", workbook("Rates"))
    add_user(client, "clerk", "editor")
    uid = next(u["id"] for u in client.get("/api/users").json() if u["username"] == "clerk")
    sign_in(client, "clerk")
    assert len(tree(client)["files"]) == 1                             # everyone can see and download
    assert client.post("/api/files/folders", json={"name": "Mine"}).status_code == 403
    assert client.post("/api/files/uploads", json={"name": "x.xlsx", "size": 3}).status_code == 403
    fid = tree(client)["files"][0]["id"]
    assert client.delete(f"/api/files/{fid}").status_code == 403

    sign_in(client, "owner")
    assert client.patch(f"/api/users/{uid}", json={"can_files": True}).json()["can_files"] is True
    sign_in(client, "clerk")
    assert client.get("/api/auth/me").json()["can_files"] is True
    assert client.delete(f"/api/files/{fid}").status_code == 200
    assert client.delete(f"/api/files/{fid}/forever").status_code == 403   # only an admin deletes for good
    sign_in(client, "owner")
    assert client.delete(f"/api/files/{fid}/forever").status_code == 200
    assert tree(client)["files"] == []
    assert [a["action"] for a in client.get("/api/audit").json()][:3] == ["file.purge", "auth.login", "file.delete"]


def test_uploads_are_checked(client, monkeypatch):
    setup_admin(client)
    monkeypatch.setattr(F, "MAX_FILE_MB", 1)
    assert client.post("/api/files/uploads", json={"name": "big.xlsx", "size": 2 * 1024 * 1024}).status_code == 413
    up = client.post("/api/files/uploads", json={"name": "a.csv", "size": 4}).json()
    assert client.put(f"/api/files/uploads/{up['upload_id']}", params={"offset": 2}, content=b"ab").status_code == 409
    assert client.put(f"/api/files/uploads/{up['upload_id']}", params={"offset": 0}, content=b"abcdef").status_code == 413
    assert client.post(f"/api/files/uploads/{up['upload_id']}/finish").status_code == 409     # not complete
    assert client.post("/api/files/uploads", json={"name": " / ", "size": 1}).status_code == 422


def test_a_file_can_become_the_master_sheet_and_its_history_is_shown(client, rich_master):
    setup_admin(client)
    r = upload(client, "Master.xlsx", rich_master.read_bytes())
    b = client.post(f"/api/files/versions/{r['version_id']}/use-as-master").json()
    assert b["status"] == "pending"
    client.post(f"/api/imports/{b['id']}/confirm")
    assert tree(client)["master"]["versions"] == 1
    hist = client.get("/api/master-sheet/versions").json()
    assert hist[0]["what"] == "Imported Master.xlsx" and hist[0]["by"] == "owner" and hist[0]["kept"]


def test_hugging_face_storage_is_used_when_configured(tmp_path, monkeypatch):
    calls = []

    class FakeApi:
        def __init__(self, token):
            calls.append(("token", token))

        def create_repo(self, repo, **kw):
            calls.append(("repo", repo, kw["private"]))

        def upload_file(self, path_or_fileobj, path_in_repo, **kw):
            calls.append(("upload", path_in_repo, open(path_or_fileobj, "rb").read()))

        def delete_file(self, path_in_repo, **kw):
            calls.append(("delete", path_in_repo))

    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    monkeypatch.setenv("HF_FILES_REPO", "me/business-files")
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    blobs = F.make_blobs(tmp_path)
    assert isinstance(blobs, F.HFBlobs) and blobs.where == "in your private Hugging Face storage"
    src = tmp_path / "up"
    src.write_bytes(b"data")
    blobs.put("k1.xlsx", src)
    assert blobs.path("k1.xlsx").read_bytes() == b"data"      # served from the local copy
    blobs.delete("k1.xlsx")
    assert calls == [("token", "hf_x"), ("repo", "me/business-files", True), ("upload", "files/k1.xlsx", b"data"),
                     ("delete", "files/k1.xlsx")]


def test_a_space_without_file_storage_refuses_uploads_instead_of_losing_them(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_FILES_REPO", raising=False)
    monkeypatch.setenv("SPACE_ID", "me/business-reports")
    blobs = F.make_blobs(tmp_path)
    assert "HF_TOKEN and HF_FILES_REPO" in blobs.where
    src = tmp_path / "up"
    src.write_bytes(b"x")
    with pytest.raises(F.HTTPException) as e:
        blobs.put("k", src)
    assert e.value.status_code == 503 and not src.exists()

    import huggingface_hub

    class BadApi:
        def __init__(self, token):
            pass

        def create_repo(self, *a, **k):
            raise RuntimeError("401 Unauthorized: invalid token")

    monkeypatch.setattr(huggingface_hub, "HfApi", BadApi)
    monkeypatch.setenv("HF_FILES_REPO", "me/business-files")
    monkeypatch.setenv("HF_TOKEN", "hf_wrong")
    assert "401 Unauthorized" in F.make_blobs(tmp_path).where
