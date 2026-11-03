// Minomeet adaptation, MIT (c) 2026 Muhammed Shareef M.
// Layout reference: Shadcn Admin, MIT (c) 2024 Sat Naing. See vendor licenses.
import { useEffect, useState } from "react";
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
  PanelLeftClose,
  PanelLeftOpen,
  Menu,
  Wifi,
  WifiOff,
} from "lucide-react";
import type { Page, Session } from "../lib/types";
import { formatDate } from "../lib/api";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { cn } from "../lib/utils";

export interface SidebarProps {
  page: Page;
  sessions: Session[];
  activeId?: string;
  navigate: (page: Page) => void;
  select: (session: Session) => void;
  create: () => void;
  disabled: boolean;
  collapsed?: boolean;
  close?: () => void;
}
export function Sidebar({
  page,
  sessions,
  activeId,
  navigate,
  select,
  create,
  disabled,
  collapsed,
  close,
}: SidebarProps) {
  const go = (action: () => void) => {
    action();
    close?.();
  };
  return (
    <aside
      className={cn("sidebar", collapsed && "sidebar-collapsed")}
      aria-label="工作空间导航"
    >
      <div className="sidebar-brand-row">
        <button
          className="brand"
          aria-label="ClassBridge 工作台"
          title="ClassBridge 工作台"
          onClick={() => go(() => navigate("home"))}
          disabled={disabled}
        >
          <span className="brand-icon">
            <AudioLines size={22} />
          </span>
          <span className="brand-name">
            ClassBridge<small>语音理解工作台</small>
          </span>
        </button>
        {close && (
          <Button
            variant="ghost"
            size="icon"
            aria-label="关闭导航"
            onClick={close}
          >
            <X size={18} />
          </Button>
        )}
      </div>
      <Button
        className="new-session"
        onClick={() => go(create)}
        disabled={disabled}
        aria-label="新建会话"
        title="新建会话"
      >
        <Plus size={18} />
        <span>新建会话</span>
      </Button>
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
            aria-current={page === id ? "page" : undefined}
            className={cn("nav-item", page === id && "selected")}
            disabled={disabled}
            onClick={() => go(() => navigate(id))}
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
            title={s.title}
            aria-current={
              s.id === activeId && page === "session" ? "page" : undefined
            }
            onClick={() => go(() => select(s))}
            className={cn(
              "recent-item",
              s.id === activeId && page === "session" && "selected",
            )}
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
        {!sessions.length && <p className="muted tiny">暂无已保存的会话</p>}
      </div>
      <div className="private-card">
        <ShieldCheck size={18} />
        <div>
          私人工作空间<small>音频与资料默认私有</small>
        </div>
      </div>
      <div className="sidebar-footer">
        ClassBridge <span>v1.0</span>
      </div>
    </aside>
  );
}

// Navigation alone switches presentation; SessionView retains its tree position.
export function ResponsiveSidebar({
  open,
  setOpen,
  ...props
}: SidebarProps & { open: boolean; setOpen: (open: boolean) => void }) {
  const [compact, setCompact] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(max-width: 900px)").matches,
  );
  useEffect(() => {
    const query = window.matchMedia("(max-width: 900px)");
    const update = () => {
      setCompact(query.matches);
      if (!query.matches) setOpen(false);
    };
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, [setOpen]);
  if (!compact) return <Sidebar {...props} />;
  return open ? (
    <Dialog
      title="工作空间导航"
      close={() => setOpen(false)}
      className="navigation-drawer"
    >
      <Sidebar {...props} collapsed={false} close={() => setOpen(false)} />
    </Dialog>
  ) : null;
}

export function Titlebar({
  title,
  dark,
  toggle,
  logout,
  disabled,
  online,
  username,
  menu,
  collapse,
  collapsed,
  menuOpen,
}: {
  title: string;
  dark: boolean;
  toggle: () => void;
  logout: () => void;
  disabled: boolean;
  online: boolean;
  username: string;
  menu: () => void;
  collapse: () => void;
  collapsed: boolean;
  menuOpen: boolean;
}) {
  return (
    <header className="topbar">
      <div className="topbar-leading">
        <Button
          variant="ghost"
          size="icon"
          className="mobile-menu-toggle"
          data-dialog-fallback-focus
          aria-label="打开导航"
          aria-expanded={menuOpen}
          onClick={menu}
        >
          <Menu size={20} />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="desktop-menu-toggle"
          aria-label={collapsed ? "展开侧边栏" : "折叠侧边栏"}
          aria-expanded={!collapsed}
          onClick={collapse}
        >
          {collapsed ? (
            <PanelLeftOpen size={19} />
          ) : (
            <PanelLeftClose size={19} />
          )}
        </Button>
        <div className="breadcrumb">
          <span>私人空间</span>
          <ChevronRight size={14} />
          <strong title={title}>{title}</strong>
        </div>
      </div>
      <div className="topbar-actions">
        <span
          className={cn("network-state", !online && "network-offline")}
          title="浏览器网络状态，不代表识别服务已连接"
        >
          {online ? <Wifi size={15} /> : <WifiOff size={15} />}
          <span>{online ? "网络可用" : "网络离线"}</span>
        </span>
        <Button
          variant="ghost"
          size="icon"
          aria-label={dark ? "切换浅色主题" : "切换深色主题"}
          onClick={toggle}
        >
          {dark ? <Sun size={18} /> : <Moon size={18} />}
        </Button>
        <span className="account-name" title={username}>
          {username}
        </span>
        <Button
          variant="ghost"
          size="icon"
          title="退出登录"
          aria-label="退出登录"
          onClick={logout}
          disabled={disabled}
        >
          <LogOut size={18} />
        </Button>
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
      <Button variant="ghost" size="icon" aria-label="关闭提示" onClick={close}>
        <X size={16} />
      </Button>
    </div>
  );
}
