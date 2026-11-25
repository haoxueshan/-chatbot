import { useCallback, useEffect, useRef, useState } from "react";
import { LoaderCircle, WifiOff } from "lucide-react";
import { Login } from "./components/Login";
import { ResponsiveSidebar, Titlebar, Toast } from "./components/Shell";
import { Home, NewSession } from "./components/Home";
import { SessionView } from "./components/SessionView";
import { Library } from "./components/Library";
import { Settings } from "./components/Settings";
import { ApiError, post, request } from "./lib/api";
import type { Mode, Page, Preferences, Session, SessionFolder, User } from "./lib/types";
import { FolderManager } from "./components/SessionFolders";

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
    [navigationOpen, setNavigationOpen] = useState(false),
    [collapsed, setCollapsed] = useState(false),
    [online, setOnline] = useState(navigator.onLine);
  const [folders, setFolders] = useState<SessionFolder[]>([]);
  const [folder, setFolder] = useState("");
  const [folderManager, setFolderManager] = useState(false);
  const [moving, setMoving] = useState(false);
  const filterRef = useRef({ search, folder });
  filterRef.current = { search, folder };
  const listVersion = useRef(0);
  const folderVersion = useRef(0);
  const loadFolders = useCallback(async () => {
    const version = ++folderVersion.current;
    try {
      const rows = await request<SessionFolder[]>("/session-folders");
      if (version === folderVersion.current) setFolders(rows);
    } catch (error) {
      if (version === folderVersion.current) throw error;
    }
  }, []);
  const current = useRef<Session | null>(session);
  current.current = session;
  const activeRef = useRef(active);
  activeRef.current = active;
  const routeRef = useRef(false);
  // UI navigation may overlap HTTP reads; only the latest route owns the view.
  const navigationVersion = useRef(0);
  const notify = useCallback((message: string) => setToast(message), []);
  const loadSessions = useCallback(
    async (q = filterRef.current.search) => {
      const version = ++listVersion.current;
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      const selected = filterRef.current.folder;
      if (selected === "unfiled") params.set("unfiled", "true");
      else if (selected) params.set("folder_id", selected);
      try {
        const query = params.toString();
        const rows = await request<Session[]>(`/sessions${query ? `?${query}` : ""}`);
        if (version === listVersion.current) setSessions(rows);
      } catch (e) {
        if (version !== listVersion.current) return;
        if (e instanceof ApiError && e.status === 401) setUser(null);
        else notify(e instanceof Error ? e.message : "无法读取会话");
      }
    },
    [notify],
  );
  const openSession = useCallback(
    async (id: string) => {
      if (activeRef.current && id !== current.current?.id) return;
      const version = ++navigationVersion.current;
      setLoading(true);
      try {
        const value = await request<Session>(`/sessions/${id}`);
        if (version !== navigationVersion.current) return;
        if (activeRef.current && id !== current.current?.id) return;
        setSession(value);
        setPage("session");
        location.hash = `session/${id}`;
      } catch (e) {
        if (version !== navigationVersion.current) return;
        notify(e instanceof Error ? e.message : "会话不存在");
      } finally {
        if (version === navigationVersion.current) setLoading(false);
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
      navigationVersion.current++;
      setLoading(false);
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
    void loadFolders().catch(e => notify(e.message));
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
  }, [user, loadSessions, loadFolders, notify, openSession]);
  useEffect(() => {
    if (user) {
      const timer = setTimeout(() => void loadSessions(search), 240);
      return () => clearTimeout(timer);
    }
  }, [search, folder, user, loadSessions]);
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
      if (activeRef.current) {
        if (current.current)
          history.replaceState(null, "", `#session/${current.current.id}`);
        return;
      }
      const hash = location.hash.slice(1);
      if (hash.startsWith("session/")) {
        if (current.current?.id !== hash.slice(8))
          void openSession(hash.slice(8));
        else setPage("session");
      } else if (["home", "settings", "library"].includes(hash)) {
        navigationVersion.current++;
        setLoading(false);
        setPage(hash as Page);
      }
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
    target_language: import("./lib/translationLanguages").TargetLanguage;
  }) => {
    const result = await post<Session>("/sessions", {
      ...data,
      folder_id: filterRef.current.folder && filterRef.current.folder !== "unfiled"
        ? filterRef.current.folder : null,
      retain_audio: data.mode === "demo" ? false : data.retain_audio,
    });
    setNewKind(null);
    await Promise.all([
      loadSessions(),
      loadFolders().catch(e => notify(e instanceof Error ? e.message : "无法刷新文件夹")),
    ]);
    await openSession(result.id);
  };
  const logout = async () => {
    if (activeRef.current) return;
    try {
      await post("/auth/logout");
      navigationVersion.current++;
      listVersion.current++;
      folderVersion.current++;
      setUser(null);
      setFolders([]);
      setFolder("");
      setSearch("");
      setFolderManager(false);
      setSession(null);
      setSessions([]);
      setPage("home");
      location.hash = "home";
    } catch (e) {
      notify(e instanceof Error ? e.message : "退出失败");
    }
  };
  const folderNavigation = {
    folders, selected: folder, disabled: active,
    select: (id: string) => {
      if (activeRef.current) return;
      listVersion.current++;
      filterRef.current.folder = id;
      setFolder(id);
      navigate("home");
    },
    manage: () => { if (!activeRef.current) setFolderManager(true); },
  };
  const moveSessions = async (ids: string[], folderId: string): Promise<boolean> => {
    if (moving || activeRef.current || !ids.length) return false;
    setMoving(true);
    try {
      await post("/session-folders/move-sessions", {
        session_ids: ids, folder_id: folderId || null,
      });
      await Promise.all([loadSessions(), loadFolders()]);
      return true;
    } catch (e) {
      notify(e instanceof Error ? e.message : "批量移动失败");
      return false;
    } finally { setMoving(false); }
  };
  const moveSession = async (id: string, folderId: string) => {
    if (moving || activeRef.current) return;
    setMoving(true);
    try {
      await request(`/sessions/${id}/folder`, {
        method: "PATCH", body: JSON.stringify({ folder_id: folderId || null }),
      });
      await Promise.all([loadSessions(), loadFolders()]);
    } catch (e) { notify(e instanceof Error ? e.message : "移动失败"); }
    finally { setMoving(false); }
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
      <ResponsiveSidebar
        open={navigationOpen}
        setOpen={setNavigationOpen}
        collapsed={collapsed}
        page={page}
        sessions={sessions}
        folderNavigation={folderNavigation}
        activeId={session?.id}
        navigate={navigate}
        select={(s) => void openSession(s.id)}
        create={() => setNewKind("classroom")}
        disabled={active}
      />
      <div className="main-shell">
        <Titlebar
          online={online}
          username={user.username}
          menu={() => setNavigationOpen(true)}
          menuOpen={navigationOpen}
          collapse={() => setCollapsed(!collapsed)}
          collapsed={collapsed}
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
              folderNavigation={folderNavigation}
              moveSession={moveSession}
              moveSessions={moveSessions}
              moving={moving}
              search={search}
              setSearch={value => {
                listVersion.current++;
                filterRef.current.search = value;
                setSearch(value);
              }}
              create={(kind) => setNewKind(kind || "classroom")}
              select={(s) => void openSession(s.id)}
              library={() => navigate("library")}
              settings={() => navigate("settings")}
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
                void loadFolders().catch(e => notify(e instanceof Error ? e.message : "无法刷新文件夹"));
              }}
            />
          )}
          {page === "library" && <Library notify={notify} />}{" "}
          {page === "settings" && (
            <Settings preferences={preferences} save={savePreferences} />
          )}
        </main>
      </div>
      {folderManager && <FolderManager
        folders={folders}
        close={() => setFolderManager(false)}
        save={async (id, name) => {
          await request(`/session-folders${id ? `/${id}` : ""}`, {
            method: id ? "PATCH" : "POST", body: JSON.stringify({ name }),
          });
          await loadFolders();
        }}
        remove={async id => {
          await request(`/session-folders/${id}`, { method: "DELETE" });
          if (filterRef.current.folder === id) {
            filterRef.current.folder = "";
            setFolder("");
          }
          await Promise.all([loadFolders(), loadSessions()]);
        }}
      />}
      {newKind && (
        <NewSession
          kind={newKind}
          close={() => setNewKind(null)}
          submit={create}
          defaultRetain={preferences.retain_audio}
          defaultTarget={preferences.target_language || "zh-CN"}
          retention={preferences.audio_retention_days}
        />
      )}
      <Toast message={toast} close={() => setToast("")} />
    </div>
  );
}
