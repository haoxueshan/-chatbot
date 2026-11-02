// Adapted from Minomeet Titlebar / Sidebar / ToastHost. MIT (c) 2026 Muhammed Shareef M.
import {
  AudioLines,
  BookOpen,
  ChevronRight,
  FileText,
  Home,
  LogOut,
  Moon,
  Plus,
  Settings,
  ShieldCheck,
  Sun,
  X,
  AlertTriangle,
} from "lucide-react";
import type { Page, Session } from "../lib/types";
import { formatDate } from "../lib/api";
export function Sidebar({
  page,
  sessions,
  activeId,
  navigate,
  select,
  create,
  disabled,
}: {
  page: Page;
  sessions: Session[];
  activeId?: string;
  navigate: (p: Page) => void;
  select: (s: Session) => void;
  create: () => void;
  disabled: boolean;
}) {
  return (
    <aside className="sidebar">
      <button
        className="brand"
        aria-label="ClassBridge 工作台"
        onClick={() => navigate("home")}
        disabled={disabled}
      >
        <span className="brand-icon">
          <AudioLines size={23} />
        </span>
        <span>
          ClassBridge<small>语音理解工作台</small>
        </span>
      </button>
      <button
        className="primary new-session"
        onClick={create}
        disabled={disabled}
      >
        <Plus size={18} />
        新建会话<kbd>＋</kbd>
      </button>
      <nav aria-label="主导航">
        {[
          { id: "home" as Page, label: "工作台", icon: Home },
          { id: "library" as Page, label: "资料库", icon: BookOpen },
          { id: "settings" as Page, label: "偏好设置", icon: Settings },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            aria-label={label}
            title={label}
            className={`nav-item ${page === id ? "selected" : ""}`}
            disabled={disabled}
            onClick={() => navigate(id)}
          >
            <Icon size={18} />
            <span>{label}</span>
            {page === id && <ChevronRight size={15} />}
          </button>
        ))}
      </nav>
      <div className="sidebar-label">
        最近会话<span>{sessions.length}</span>
      </div>
      <div className="recent-nav">
        {sessions.slice(0, 10).map((s) => (
          <button
            key={s.id}
            disabled={disabled && s.id !== activeId}
            onClick={() => select(s)}
            className={`recent-item ${s.id === activeId && page === "session" ? "selected" : ""}`}
          >
            <FileText size={16} />
            <span>
              {s.title}
              <small>
                {formatDate(s.created_at)}
                {s.mode === "demo" ? " · 模拟" : ""}
              </small>
            </span>
          </button>
        ))}
        {!sessions.length && (
          <p className="muted tiny">第一段灵感，从这里开始。</p>
        )}
      </div>
      <div className="private-card">
        <ShieldCheck size={18} />
        <div>
          私人工作空间<small>你的课堂，只对你开放</small>
        </div>
        <i />
      </div>
      <div className="sidebar-footer">
        CLASSBRIDGE <span>v1.0</span>
      </div>
    </aside>
  );
}
export function Titlebar({
  title,
  dark,
  toggle,
  logout,
  disabled,
}: {
  title: string;
  dark: boolean;
  toggle: () => void;
  logout: () => void;
  disabled: boolean;
}) {
  return (
    <header className="topbar">
      <div className="breadcrumb">
        <span>我的空间</span>
        <ChevronRight size={14} />
        <strong>{title}</strong>
      </div>
      <div className="topbar-actions">
        <span className="private-label">
          <ShieldCheck size={14} />
          私人访问
        </span>
        <button
          className="icon-button"
          aria-label={dark ? "切换浅色主题" : "切换深色主题"}
          onClick={toggle}
        >
          {dark ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        <button
          className="avatar"
          title="退出登录"
          aria-label="退出登录"
          onClick={logout}
          disabled={disabled}
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  );
}
export function Toast({
  message,
  close,
}: {
  message: string;
  close: () => void;
}) {
  if (!message) return null;
  return (
    <div className="toast toast-enter" role="status">
      <AlertTriangle size={18} />
      <span>{message}</span>
      <button className="icon-button" aria-label="关闭提示" onClick={close}>
        <X size={16} />
      </button>
    </div>
  );
}
