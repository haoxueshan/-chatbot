import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Home as HomeIcon,
  LoaderCircle,
  Settings as SettingsIcon,
  WifiOff,
} from "lucide-react";
import { Login } from "./components/Login";
import { Sidebar, Titlebar, Toast } from "./components/Shell";
import { Home, NewSession } from "./components/Home";
import { SessionView } from "./components/SessionView";
import { Library } from "./components/Library";
import { Settings } from "./components/Settings";
import { ApiError, post, request } from "./lib/api";
import type { Mode, Page, Preferences, Session, User } from "./lib/types";

const defaultPreferences: Preferences = {
  asr_language_mode: "auto",
  theme: "light",
  subtitle_size: 24,
  show_original: true,
  retain_audio: false,
  audio_retention_days: 7,
  terms: [],
};
export default function App() {
  const [user, setUser] = useState<User | null>(null),
    [authLoading, setAuthLoading] = useState(true),
    [page, setPage] = useState<Page>("home"),
    [sessions, setSessions] = useState<Session[]>([]),
    [session, setSession] = useState<Session | null>(null),
    [preferences, setPreferences] = useState(defaultPreferences),
    [search, setSearch] = useState(""),
    [toast, setToast] = useState(""),
    [newKind, setNewKind] = useState<string | null>(null),
    [active, setActive] = useState(false),
    [loading, setLoading] = useState(false),
    [online, setOnline] = useState(navigator.onLine);
  const current = useRef<Session | null>(session);
  current.current = session;
  const activeRef = useRef(active);
  activeRef.current = active;
  const routeRef = useRef(false);
  const notify = useCallback((message: string) => setToast(message), []);
  const loadSessions = useCallback(
    async (q = "") => {
      try {
        setSessions(
          await request<Session[]>(
            `/sessions${q ? `?q=${encodeURIComponent(q)}` : ""}`,
          ),
        );
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) setUser(null);
        else notify(e instanceof Error ? e.message : "无法读取会话");
      }
    },
    [notify],
  );
  const openSession = useCallback(
    async (id: string) => {
      if (activeRef.current && id !== current.current?.id) return;
      setLoading(true);
      try {
        const value = await request<Session>(`/sessions/${id}`);
        setSession(value);
        setPage("session");
        location.hash = `session/${id}`;
      } catch (e) {
        notify(e instanceof Error ? e.message : "会话不存在");
      } finally {
        setLoading(false);
      }
    },
    [notify],
  );
  const refresh = useCallback(() => {
    const id = current.current?.id;
    if (id)
      void request<Session>(`/sessions/${id}`)
        .then((value) => {
          if (current.current?.id === id) setSession(value);
        })
        .catch(() => {});
  }, []);
  const navigate = useCallback(
    (target: Page) => {
      if (activeRef.current) return;
      setPage(target);
      location.hash = target;
      if (target === "home") void loadSessions();
    },
    [loadSessions],
  );
  useEffect(() => {
    request<User>("/auth/me")
      .then(setUser)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401))
          notify("无法连接服务器，请确认 API 已启动");
      })
      .finally(() => setAuthLoading(false));
  }, [notify]);
  useEffect(() => {
    if (!user) {
      routeRef.current = false;
      return;
    }
    void loadSessions();
    void request<Preferences>("/settings")
      .then((p) =>
        setPreferences({ ...defaultPreferences, ...p, terms: p.terms || [] }),
      )
      .catch((e) => notify(e.message));
    if (!routeRef.current) {
      routeRef.current = true;
      const route = location.hash.slice(1);
      if (route.startsWith("session/")) void openSession(route.slice(8));
      else if (["home", "settings", "library"].includes(route))
        setPage(route as Page);
    }
  }, [user, loadSessions, notify, openSession]);
  useEffect(() => {
    if (user) {
      const timer = setTimeout(() => void loadSessions(search), 240);
      return () => clearTimeout(timer);
    }
  }, [search, user, loadSessions]);
  useEffect(() => {
    document.documentElement.dataset.theme = preferences.theme;
    document.documentElement.classList.toggle(
      "dark",
      preferences.theme === "dark",
    );
  }, [preferences.theme]);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  useEffect(() => {
    const handle = () => {
      if (activeRef.current) return;
      const hash = location.hash.slice(1);
      if (hash.startsWith("session/")) {
        if (current.current?.id !== hash.slice(8))
          void openSession(hash.slice(8));
      } else if (["home", "settings", "library"].includes(hash))
        setPage(hash as Page);
    };
    window.addEventListener("hashchange", handle);
    return () => window.removeEventListener("hashchange", handle);
  }, [openSession]);
  const savePreferences = async (value: Preferences) => {
    const next = await request<Preferences>("/settings", {
      method: "PATCH",
      body: JSON.stringify(value),
    });
    setPreferences({ ...defaultPreferences, ...next });
  };
  const create = async (data: {
    title: string;
    kind: string;
    mode: Mode;
    retain_audio: boolean;
  }) => {
    const result = await post<Session>("/sessions", {
      ...data,
      retain_audio: data.mode === "demo" ? false : data.retain_audio,
    });
    setNewKind(null);
    await loadSessions();
    await openSession(result.id);
  };
  const logout = async () => {
    try {
      await post("/auth/logout");
      setUser(null);
      setSession(null);
      setSessions([]);
      setPage("home");
      location.hash = "home";
    } catch (e) {
      notify(e instanceof Error ? e.message : "退出失败");
    }
  };
  if (authLoading)
    return (
      <div className="app-loading">
        <LoaderCircle className="spin" size={28} />
        <p>正在打开你的工作台…</p>
      </div>
    );
  if (!user)
    return (
      <>
        <Login done={setUser} />
        <Toast message={toast} close={() => setToast("")} />
      </>
    );
  return (
    <div className="app-shell">
      <Sidebar
        page={page}
        sessions={sessions}
        activeId={session?.id}
        navigate={navigate}
        select={(s) => void openSession(s.id)}
        create={() => setNewKind("classroom")}
        disabled={active}
      />
      <div className="main-shell">
        <Titlebar
          title={
            page === "home"
              ? "工作台"
              : page === "library"
                ? "资料库"
                : page === "settings"
                  ? "偏好设置"
                  : session?.title || "实时会话"
          }
          dark={preferences.theme === "dark"}
          toggle={() => {
            const next = {
              ...preferences,
              theme:
                preferences.theme === "dark"
                  ? ("light" as const)
                  : ("dark" as const),
            };
            setPreferences(next);
            void savePreferences(next).catch((e) => notify(e.message));
          }}
          logout={() => void logout()}
          disabled={active}
        />
        {!online && (
          <div className="offline-banner" role="alert">
            <WifiOff size={15} />
            网络已断开。已保存内容不会丢失，实时采集需要连接服务器。
          </div>
        )}
        <main className="main-content">
          {loading && (
            <div className="view-loading">
              <LoaderCircle className="spin" />
              正在读取会话…
            </div>
          )}
          {page === "home" && (
            <Home
              sessions={sessions}
              search={search}
              setSearch={setSearch}
              create={(kind) => setNewKind(kind || "classroom")}
              select={(s) => void openSession(s.id)}
              library={() => navigate("library")}
            />
          )}{" "}
          {page === "session" && session && (
            <SessionView
              key={session.id}
              session={session}
              preferences={preferences}
              onActivity={setActive}
              refresh={refresh}
              back={() => navigate("home")}
              notify={notify}
              openSession={(id) => void openSession(id)}
              deleted={() => {
                setSession(null);
                navigate("home");
              }}
            />
          )}
          {page === "library" && <Library notify={notify} />}{" "}
          {page === "settings" && (
            <Settings preferences={preferences} save={savePreferences} />
          )}
        </main>
        <nav className="mobile-navigation" aria-label="移动端导航">
          {[
            { id: "home" as Page, label: "工作台", icon: HomeIcon },
            { id: "library" as Page, label: "资料库", icon: BookOpen },
            { id: "settings" as Page, label: "设置", icon: SettingsIcon },
          ].map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={page === id ? "active" : ""}
              disabled={active}
              onClick={() => navigate(id)}
            >
              <Icon size={19} />
              {label}
            </button>
          ))}
        </nav>
      </div>
      {newKind && (
        <NewSession
          kind={newKind}
          close={() => setNewKind(null)}
          submit={create}
          defaultRetain={preferences.retain_audio}
          retention={preferences.audio_retention_days}
        />
      )}
      <Toast message={toast} close={() => setToast("")} />
    </div>
  );
}
