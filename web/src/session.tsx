import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, query, type Reports, type Role, type Status, type User } from "./api";
import { today } from "./format";

// ------------------------------------------------------------------ signed-in user
interface AuthState {
  user: User | null;
  loading: boolean;
  setUser: (u: User | null) => void;
  signOut: () => Promise<void>;
}

const AuthCtx = createContext<AuthState>(null!);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<User>("/auth/me").then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
    const out = () => setUser(null);
    window.addEventListener("signed-out", out);
    return () => window.removeEventListener("signed-out", out);
  }, []);

  const signOut = useCallback(async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    setUser(null);
  }, []);

  return <AuthCtx.Provider value={{ user, loading, setUser, signOut }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);

const RANK: Record<Role, number> = { viewer: 0, editor: 1, admin: 2 };
export const can = (user: User | null, role: Role) => !!user && RANK[user.role] >= RANK[role];

// ------------------------------------------------------------------ report filters and data
export interface Filters {
  as_of: string;
  date_from: string;
  date_to: string;
  products: string[];
  types: string[];
  sub_types: string[];
  companies: string[];
}

const EMPTY: Filters = { as_of: today(), date_from: "", date_to: "", products: [], types: [], sub_types: [],
  companies: [] };

interface DataState {
  filters: Filters;
  setFilters: (f: Filters) => void;
  status: Status | null;
  reports: Reports | null;
  loading: boolean;
  error: string;
  reload: () => void;
  filterQuery: string;
  /** the data version; changes when anyone saves an entry or an import */
  version: string;
  /** a short note when someone else changed the data ("Sales invoice 12 saved by ravi") */
  news: string;
  clearNews: () => void;
}

const DataCtx = createContext<DataState>(null!);

export function DataProvider({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [status, setStatus] = useState<Status | null>(null);
  const [reports, setReports] = useState<Reports | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const filterQuery = query({ ...filters });

  useEffect(() => {
    api<Status>("/status").then(setStatus).catch(() => undefined);
  }, [tick]);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api<Reports>(`/reports${filterQuery}`)
      .then((r) => live && (setReports(r), setError("")))
      .catch((e) => live && setError(e.message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [filterQuery, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  // live updates: a cheap check every few seconds; when the data changed, everything reloads
  const [version, setVersion] = useState("");
  const [news, setNews] = useState("");
  const { user } = useAuth();
  useEffect(() => {
    let last = "";
    const check = () => {
      if (document.hidden) return;
      api<{ version: string; last_change: string | null; by: string | null }>("/version").then((v) => {
        if (last && v.version !== last) {
          setTick((t) => t + 1);
          if (v.by !== user?.username && v.last_change) setNews(`${v.last_change}${v.by ? ` (by ${v.by})` : ""}`);
        }
        last = v.version;
        setVersion(v.version);
      }).catch(() => undefined);
    };
    check();
    const id = window.setInterval(check, 8000);
    document.addEventListener("visibilitychange", check);
    return () => { window.clearInterval(id); document.removeEventListener("visibilitychange", check); };
  }, [tick, user?.username]);
  const clearNews = useCallback(() => setNews(""), []);

  return (
    <DataCtx.Provider value={{ filters, setFilters, status, reports, loading, error, reload, filterQuery, version, news,
      clearNews }}>
      {children}
    </DataCtx.Provider>
  );
}

export const useData = () => useContext(DataCtx);
