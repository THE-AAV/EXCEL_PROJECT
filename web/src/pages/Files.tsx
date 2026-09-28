import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import DataGrid from "../components/DataGrid";
import { when } from "../format";
import { can, useAuth, useData } from "../session";

interface Sheet { name: string; rows: number | null; cols: number | null }
interface Folder { id: number; name: string; parent_id: number | null; created_by: string | null }
interface FileRow {
  id: number; name: string; folder_id: number | null; deleted_at: string | null; deleted_by: string | null;
  version: number; versions: number; version_id: number | null; size: number; sheets: Sheet[];
  changed_at: string; changed_by: string | null; created_by: string | null;
}
interface Tree {
  folders: Folder[]; files: FileRow[]; where: string;
  master: { changed_at: string; changed_by: string | null; last_change: string; versions: number } | null;
}
interface Version { id: number; number: number; size: number; sheets: Sheet[]; note: string; by: string | null; at: string }
interface Activity { at: string; by: string; action: string; details: Record<string, unknown> }
interface MasterVersion { id: number; what: string; status: string; by: string | null; at: string; kept: boolean }
interface Upload { key: string; name: string; size: number; sent: number; state: "sending" | "done" | "failed"; error?: string }
type Sel = { kind: "file"; id: number } | { kind: "master" } | null;

const EXCEL = /\.(xlsx|xlsm|xltx|xltm)$/i;
const size = (b: number) => b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(0)} KB` :
  b < 1073741824 ? `${(b / 1048576).toFixed(1)} MB` : `${(b / 1073741824).toFixed(2)} GB`;
const ACTIONS: Record<string, string> = {
  "file.upload": "Uploaded", "file.version": "Uploaded a new version", "file.edit": "Renamed / moved",
  "file.delete": "Deleted", "file.restore": "Brought back", "file.download": "Downloaded",
};

function Icon({ kind }: { kind: "folder" | "excel" | "file" | "master" }) {
  const color = { folder: "#e0a526", excel: "#1d7044", file: "#6b7a8c", master: "#1f4e79" }[kind];
  return kind === "folder" ? (
    <svg className="ficon" viewBox="0 0 24 24" aria-hidden><path fill={color} d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></svg>
  ) : (
    <svg className="ficon" viewBox="0 0 24 24" aria-hidden>
      <path fill={color} d="M6 2h8l5 5v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" />
      <path fill="#fff" opacity=".45" d="M14 2v5h5z" />
      {kind !== "file" && <text x="12" y="17.5" textAnchor="middle" fontSize="8" fontWeight="700" fill="#fff">{kind === "master" ? "M" : "X"}</text>}
    </svg>
  );
}

/** Sends a file in pieces, so big files (up to 1 GB) work and show their progress. */
async function sendFile(file: File, target: { folder_id?: number | null; file_id?: number }, progress: (sent: number) => void) {
  const start = await api<{ upload_id: string; chunk_size: number }>("/files/uploads", {
    method: "POST", json: { name: file.name, size: file.size, ...target },
  });
  const id = start.upload_id;
  try {
    for (let off = 0; off < file.size || (off === 0 && file.size === 0); off += start.chunk_size) {
      const piece = file.slice(off, off + start.chunk_size);
      for (let attempt = 1; ; attempt++) {
        try {
          await api(`/files/uploads/${id}?offset=${off}`, { method: "PUT", body: piece });
          break;
        } catch (e) {
          if (attempt >= 3) throw e;
          await new Promise((r) => setTimeout(r, 1500 * attempt));
        }
      }
      progress(Math.min(off + start.chunk_size, file.size));
      if (file.size === 0) break;
    }
    return await api<{ file_id: number; version: number; new: boolean; name: string }>(`/files/uploads/${id}/finish`, { method: "POST" });
  } catch (e) {
    api(`/files/uploads/${id}`, { method: "DELETE" }).catch(() => undefined);
    throw e;
  }
}

export default function Files() {
  const { user } = useAuth();
  const { version: dataVersion } = useData();
  const mayChange = !!user && (user.role === "admin" || !!user.can_files);
  const isAdmin = can(user, "admin");
  const [tree, setTree] = useState<Tree | null>(null);
  const [folder, setFolder] = useState<number | null>(null);
  const [sel, setSel] = useState<Sel>(null);
  const [trash, setTrash] = useState(false);
  const [search, setSearch] = useState("");
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [msg, setMsg] = useState<{ good: boolean; text: string } | null>(null);
  const [drag, setDrag] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api<Tree>("/files").then(setTree).catch((e) => setMsg({ good: false, text: e.message })), []);
  useEffect(() => { load(); }, [load, dataVersion]);
  useEffect(() => { const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);

  const act = async (fn: () => Promise<unknown>, done?: string) => {
    setMsg(null);
    try { await fn(); if (done) setMsg({ good: true, text: done }); await load(); return true; } catch (e) {
      setMsg({ good: false, text: (e as Error).message }); return false;
    }
  };

  const upload = async (list: FileList | File[], target: { folder_id?: number | null; file_id?: number }) => {
    for (const file of Array.from(list)) {
      const key = `${file.name}-${Date.now()}-${Math.random()}`;
      setUploads((u) => [{ key, name: file.name, size: file.size, sent: 0, state: "sending" as const }, ...u].slice(0, 8));
      const set = (p: Partial<Upload>) => setUploads((u) => u.map((x) => (x.key === key ? { ...x, ...p } : x)));
      try {
        const r = await sendFile(file, target, (sent) => set({ sent }));
        set({ state: "done", sent: file.size, name: r.new ? `${r.name}` : `${r.name} (saved as version ${r.version})` });
        await load();
        setSel({ kind: "file", id: r.file_id });
      } catch (e) {
        set({ state: "failed", error: (e as Error).message });
      }
    }
  };

  const folders = tree?.folders ?? [];
  const byId = useMemo(() => new Map(folders.map((f) => [f.id, f])), [folders]);
  const path = useMemo(() => {
    const out: Folder[] = [];
    for (let f = folder != null ? byId.get(folder) : undefined; f; f = f.parent_id != null ? byId.get(f.parent_id) : undefined) out.unshift(f);
    return out;
  }, [folder, byId]);
  const where = (id: number | null) => {
    const names: string[] = [];
    for (let f = id != null ? byId.get(id) : undefined; f; f = f.parent_id != null ? byId.get(f.parent_id) : undefined) names.unshift(f.name);
    return ["Files", ...names].join(" › ");
  };
  if (!tree) return msg ? <div className="error">{msg.text}</div> : <span className="spinner" />;

  const q = search.trim().toLowerCase();
  const subfolders = trash || q ? [] : folders.filter((f) => f.parent_id === folder);
  const shown = tree.files.filter((f) => (trash ? !!f.deleted_at : !f.deleted_at)
    && (q ? f.name.toLowerCase().includes(q) || f.sheets.some((s) => s.name.toLowerCase().includes(q)) : trash || f.folder_id === folder));
  const selected = sel?.kind === "file" ? tree.files.find((f) => f.id === sel.id) : undefined;
  const deletedCount = tree.files.filter((f) => f.deleted_at).length;

  return (
    <>
      <p className="hint">All the files of the business in one place, like the file manager on Windows: folders, the
        Excel sheets inside each file, and every earlier version with who uploaded it. Files are kept in {tree.where}.
        {!mayChange && " You can open and download files; an admin can allow you to upload and delete them."}</p>
      {msg && <div className={msg.good ? "notice good" : "error"}>{msg.text}</div>}
      <div className="files">
        <aside className="ftree">
          <button className={`ftree-item ${!trash && folder === null && !q ? "active" : ""}`}
            onClick={() => { setTrash(false); setFolder(null); setSearch(""); }}><Icon kind="folder" /> Files</button>
          <FolderTree folders={folders} parent={null} depth={1} current={trash || q ? undefined : folder}
            open={(id) => { setTrash(false); setSearch(""); setFolder(id); setSel(null); }} />
          <button className={`ftree-item trash ${trash ? "active" : ""}`} onClick={() => { setTrash(true); setSel(null); }}>
            🗑 Recently deleted{deletedCount > 0 && <span className="muted"> ({deletedCount})</span>}</button>
        </aside>

        <section className={`fmain ${drag ? "drag" : ""}`}
          onDragOver={(e) => { if (mayChange && !trash) { e.preventDefault(); setDrag(true); } }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); if (mayChange && !trash && e.dataTransfer.files.length) upload(e.dataTransfer.files, { folder_id: folder }); }}>
          <div className="ftools">
            <div className="crumbs">
              {trash ? <b>Recently deleted</b> : q ? <b>Search results</b> : <>
                <button className="link" onClick={() => setFolder(null)}>Files</button>
                {path.map((f) => <span key={f.id}> › <button className="link" onClick={() => setFolder(f.id)}>{f.name}</button></span>)}
              </>}
            </div>
            <input className="fsearch" placeholder="Search files and sheets…" value={search} onChange={(e) => setSearch(e.target.value)} />
            {mayChange && !trash && <>
              <button className="secondary" onClick={() => {
                const name = prompt("Name of the new folder");
                if (name) act(() => api("/files/folders", { method: "POST", json: { name, parent_id: folder } }), `Folder ${name} made`);
              }}>New folder</button>
              <button className="primary" onClick={() => picker.current?.click()}>Upload files</button>
              <input ref={picker} type="file" multiple hidden onChange={(e) => { if (e.target.files) upload(e.target.files, { folder_id: folder }); e.target.value = ""; }} />
            </>}
          </div>

          {uploads.length > 0 && (
            <div className="uploads">
              {uploads.map((u) => (
                <div key={u.key} className={`upload ${u.state}`}>
                  <span className="uname">{u.name}</span>
                  {u.state === "sending" ? <progress value={u.sent} max={u.size || 1} /> : null}
                  <span className="muted small">{u.state === "sending" ? `${size(u.sent)} of ${size(u.size)}` :
                    u.state === "done" ? "Uploaded" : `Not uploaded: ${u.error}`}</span>
                </div>
              ))}
              {uploads.every((u) => u.state !== "sending") && <button className="link" onClick={() => setUploads([])}>Clear</button>}
            </div>
          )}

          <table className="flist">
            <thead><tr><th>Name</th><th>Sheets</th><th className="num">Size</th><th>Changed</th><th>By</th></tr></thead>
            <tbody>
              {!trash && !q && folder === null && tree.master && (
                <tr className={sel?.kind === "master" ? "sel" : ""} onClick={() => setSel({ kind: "master" })}>
                  <td><Icon kind="master" /> <b>Master Sheet (live).xlsx</b> <span className="badge live">live</span></td>
                  <td className="muted">Purchase, Sales, PO, SO…</td><td className="num muted">—</td>
                  <td>{when(tree.master.changed_at)}</td><td>{tree.master.changed_by}</td>
                </tr>
              )}
              {subfolders.map((f) => (
                <tr key={`d${f.id}`} onDoubleClick={() => setFolder(f.id)} onClick={() => setFolder(f.id)}>
                  <td><Icon kind="folder" /> {f.name}</td>
                  <td className="muted">{tree.files.filter((x) => x.folder_id === f.id && !x.deleted_at).length} files</td>
                  <td /><td /><td>{f.created_by}</td>
                </tr>
              ))}
              {shown.map((f) => (
                <tr key={f.id} className={selected?.id === f.id ? "sel" : ""} onClick={() => setSel({ kind: "file", id: f.id })}>
                  <td><Icon kind={EXCEL.test(f.name) ? "excel" : "file"} /> {f.name}
                    {(q || trash) && <span className="muted small"> · {where(f.folder_id)}</span>}</td>
                  <td className="muted">{f.sheets.length ? `${f.sheets.length}: ${f.sheets.map((s) => s.name).join(", ")}` : ""}</td>
                  <td className="num">{size(f.size)}</td>
                  <td>{when(trash ? f.deleted_at : f.changed_at)}</td>
                  <td>{trash ? f.deleted_by : f.changed_by}</td>
                </tr>
              ))}
              {!subfolders.length && !shown.length && !(tree.master && !trash && !q && folder === null) && (
                <tr><td colSpan={5} className="muted empty">{trash ? "Nothing has been deleted." : q ? "No file or sheet has that name." :
                  mayChange ? "This folder is empty. Drag files here, or use Upload files." : "This folder is empty."}</td></tr>
              )}
            </tbody>
          </table>
          {mayChange && !trash && <p className="muted small">Tip: drag files from your computer onto this list to upload
            them here. Uploading a file with the same name as one in this folder saves it as a new version of that file.</p>}
        </section>
      </div>

      {sel?.kind === "master" && tree.master && <MasterPanel isAdmin={isAdmin} onClose={() => setSel(null)} />}
      {selected && (
        <FilePanel key={`${selected.id}-${selected.version}`} file={selected} folders={folders} where={where}
          mayChange={mayChange} isAdmin={isAdmin} act={act} upload={upload} onClose={() => setSel(null)} />
      )}
    </>
  );
}

function FolderTree({ folders, parent, depth, current, open }: {
  folders: Folder[]; parent: number | null; depth: number; current: number | null | undefined; open: (id: number) => void;
}) {
  return (
    <>
      {folders.filter((f) => f.parent_id === parent).map((f) => (
        <div key={f.id}>
          <button className={`ftree-item ${current === f.id ? "active" : ""}`} style={{ paddingLeft: 8 + depth * 14 }}
            onClick={() => open(f.id)}><Icon kind="folder" /> {f.name}</button>
          <FolderTree folders={folders} parent={f.id} depth={depth + 1} current={current} open={open} />
        </div>
      ))}
    </>
  );
}

function FilePanel({ file, folders, where, mayChange, isAdmin, act, upload, onClose }: {
  file: FileRow; folders: Folder[]; where: (id: number | null) => string; mayChange: boolean; isAdmin: boolean;
  act: (fn: () => Promise<unknown>, done?: string) => Promise<boolean>;
  upload: (list: FileList | File[], target: { file_id?: number }) => void; onClose: () => void;
}) {
  const [tab, setTab] = useState<"sheets" | "versions" | "activity">(file.sheets.length ? "sheets" : "versions");
  const [sheet, setSheet] = useState(file.sheets[0]?.name ?? "");
  const [versions, setVersions] = useState<Version[]>([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [grid, setGrid] = useState<{ cols: [string, string][]; rows: Record<string, unknown>[]; more: boolean } | null>(null);
  const [gridErr, setGridErr] = useState("");
  const [moving, setMoving] = useState(false);
  const newVersion = useRef<HTMLInputElement>(null);
  const deleted = !!file.deleted_at;

  useEffect(() => {
    api<Version[]>(`/files/${file.id}/versions`).then(setVersions).catch(() => undefined);
    api<Activity[]>(`/files/${file.id}/activity`).then(setActivity).catch(() => undefined);
  }, [file.id, file.version, file.deleted_at, file.name, file.folder_id]);
  useEffect(() => {
    if (!sheet || !file.version_id) return;
    setGrid(null); setGridErr("");
    api<typeof grid>(`/files/versions/${file.version_id}/sheet?name=${encodeURIComponent(sheet)}`)
      .then(setGrid).catch((e) => setGridErr(e.message));
  }, [sheet, file.version_id]);

  return (
    <div className="card fpanel">
      <div className="card-head">
        <h3><Icon kind={EXCEL.test(file.name) ? "excel" : "file"} /> {file.name}</h3>
        <button className="link" onClick={onClose}>Close</button>
      </div>
      <p className="muted small">{where(file.folder_id)} · version {file.version} of {file.versions} · {size(file.size)} ·
        added by {file.created_by}{deleted && ` · deleted by ${file.deleted_by} ${when(file.deleted_at)}`}</p>
      <div className="actions">
        {file.version_id && <a className="button primary" href={`/api/files/versions/${file.version_id}/download`}>Download</a>}
        {mayChange && !deleted && <>
          <button className="secondary" onClick={() => newVersion.current?.click()}>Upload new version</button>
          <input ref={newVersion} type="file" hidden onChange={(e) => { if (e.target.files) upload(e.target.files, { file_id: file.id }); e.target.value = ""; }} />
          <button className="secondary" onClick={() => {
            const name = prompt("New name", file.name);
            if (name && name !== file.name) act(() => api(`/files/${file.id}`, { method: "PATCH", json: { name } }), "Renamed");
          }}>Rename</button>
          <button className="secondary" onClick={() => setMoving(!moving)}>Move</button>
          <button className="secondary danger" onClick={() => {
            if (confirm(`Delete ${file.name}? It goes to Recently deleted, from where it can be brought back.`))
              act(() => api(`/files/${file.id}`, { method: "DELETE" }), `${file.name} deleted`).then((ok) => ok && onClose());
          }}>Delete</button>
        </>}
        {mayChange && deleted && <button className="secondary" onClick={() => act(() => api(`/files/${file.id}/restore`, { method: "POST" }), `${file.name} brought back`)}>Bring back</button>}
        {isAdmin && deleted && <button className="secondary danger" onClick={() => {
          if (confirm(`Delete ${file.name} and all its versions for good? This can't be undone.`))
            act(() => api(`/files/${file.id}/forever`, { method: "DELETE" }), `${file.name} deleted for good`).then((ok) => ok && onClose());
        }}>Delete for good</button>}
        {isAdmin && !deleted && EXCEL.test(file.name) && file.version_id && (
          <button className="secondary" title="Makes this workbook the business data: you see a preview on the Import page first"
            onClick={() => act(() => api(`/files/versions/${file.version_id}/use-as-master`, { method: "POST" }),
              "Preview ready: open the Import page to check it and confirm")}>Use as Master Sheet</button>
        )}
      </div>
      {moving && (
        <div className="actions">
          <span className="muted">Move to:</span>
          <select defaultValue="" onChange={(e) => {
            const v = e.target.value;
            if (v === "") return;
            act(() => api(`/files/${file.id}`, { method: "PATCH", json: { folder_id: v === "top" ? null : Number(v), move: true } }), "Moved")
              .then(() => setMoving(false));
          }}>
            <option value="">Choose a folder…</option>
            <option value="top">Files (top level)</option>
            {folders.map((f) => <option key={f.id} value={f.id}>{where(f.id).replace(/^Files › /, "")}</option>)}
          </select>
        </div>
      )}
      <div className="tabs">
        {file.sheets.length > 0 && <button className={tab === "sheets" ? "active" : ""} onClick={() => setTab("sheets")}>Sheets ({file.sheets.length})</button>}
        <button className={tab === "versions" ? "active" : ""} onClick={() => setTab("versions")}>Versions ({file.versions})</button>
        <button className={tab === "activity" ? "active" : ""} onClick={() => setTab("activity")}>Who did what</button>
      </div>
      {tab === "sheets" && (
        <>
          <div className="sheet-tabs">
            {file.sheets.map((s) => (
              <button key={s.name} className={s.name === sheet ? "active" : ""} onClick={() => setSheet(s.name)}>
                {s.name} <span className="muted small">{s.rows === 0 ? "empty" : s.rows != null ? `${s.rows.toLocaleString("en-IN")} ${s.rows === 1 ? "row" : "rows"} × ${s.cols}` : ""}</span>
              </button>
            ))}
          </div>
          {gridErr ? <div className="error">{gridErr}</div> : !grid ? <span className="spinner" /> : (
            <>
              <DataGrid key={sheet} rows={grid.rows} cols={[["_n", "#"], ...grid.cols]} height={420} totals={false} wide
                pin={["_n"]} exportName={`${file.name} - ${sheet}`} emptyText="This sheet is empty" />
              {grid.more && <p className="muted small">Showing the first 200 rows. Download the file to see all of it.</p>}
            </>
          )}
        </>
      )}
      {tab === "versions" && (
        <table className="plain wide">
          <thead><tr><th>Version</th><th>When</th><th>By</th><th>What</th><th>Sheets</th><th className="num">Size</th><th /></tr></thead>
          <tbody>{versions.map((v) => (
            <tr key={v.id}>
              <td>{v.number}{v.number === file.version && <span className="badge"> current</span>}</td>
              <td>{when(v.at)}</td><td>{v.by}</td><td>{v.note}</td>
              <td className="small">{v.sheets.map((s) => s.name).join(", ")}</td>
              <td className="num">{size(v.size)}</td>
              <td><a className="link" href={`/api/files/versions/${v.id}/download`}>Download</a></td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {tab === "activity" && (
        <table className="plain wide">
          <thead><tr><th>When</th><th>Who</th><th>What</th></tr></thead>
          <tbody>{activity.map((a, i) => (
            <tr key={i}><td>{when(a.at)}</td><td>{a.by}</td>
              <td>{ACTIONS[a.action] ?? a.action}{a.details.version ? ` (version ${a.details.version})` : ""}
                {a.details.renamed_to ? ` → ${a.details.renamed_to}` : ""}{a.details.moved_to ? ` → ${a.details.moved_to}` : ""}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

function MasterPanel({ isAdmin, onClose }: { isAdmin: boolean; onClose: () => void }) {
  const [hist, setHist] = useState<MasterVersion[] | null>(null);
  const { version } = useData();
  useEffect(() => { api<MasterVersion[]>("/master-sheet/versions").then(setHist).catch(() => setHist([])); }, [version]);
  const label = (s: string): ReactNode => s === "active" ? <span className="badge"> current</span> :
    s === "undone" ? <span className="badge"> undone</span> : null;
  return (
    <div className="card fpanel">
      <div className="card-head">
        <h3><Icon kind="master" /> Master Sheet (live).xlsx</h3>
        <button className="link" onClick={onClose}>Close</button>
      </div>
      <p className="muted small">The workbook the reports are made from. It changes by itself with every entry anyone
        saves on Enter transactions, so it is always up to date; the list below shows every change and who made it.</p>
      <div className="actions">
        <a className="button primary" href="/api/master-sheet">Download the current Master Sheet</a>
      </div>
      {!hist ? <span className="spinner" /> : (
        <table className="plain wide">
          <thead><tr><th>When</th><th>Who</th><th>Change</th>{isAdmin && <th />}</tr></thead>
          <tbody>{hist.map((h) => (
            <tr key={h.id} className={h.status === "undone" ? "inactive" : ""}>
              <td>{when(h.at)}</td><td>{h.by}</td><td>{h.what}{label(h.status)}</td>
              {isAdmin && <td>{h.kept && <a className="link" href={`/api/imports/${h.id}/file`}>Download this version</a>}</td>}
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
