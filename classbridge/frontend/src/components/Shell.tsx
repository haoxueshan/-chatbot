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
import { formatDate, formatNumber } from "../i18n";
import { useI18n } from "../i18n/I18nProvider";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { cn } from "../lib/utils";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { FolderNavigation, type FolderNavigationProps } from "./SessionFolders";

export interface SidebarProps {
  page: Page;
  sessions: Session[];
  folderNavigation?: FolderNavigationProps;
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
  folderNavigation,
  navigate,
  select,
  create,
  disabled,
  collapsed,
  close,
}: SidebarProps) {
  const { t, language } = useI18n();
  const go = (action: () => void) => {
    action();
    close?.();
  };
  return (
    <aside
      className={cn("sidebar", collapsed && "sidebar-collapsed")}
      aria-label={t("navigation.workspace")}
    >
      <div className="sidebar-brand-row">
        <button
          className="brand"
          aria-label={t("navigation.brand")}
          title={t("navigation.brand")}
          onClick={() => go(() => navigate("home"))}
          disabled={disabled}
        >
          <span className="brand-icon">
            <AudioLines size={22} />
          </span>
          <span className="brand-name">
            ClassBridge<small>{t("auth.brand")}</small>
          </span>
        </button>
        {close && (
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("navigation.close")}
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
        aria-label={t("sessions.new")}
        title={t("sessions.new")}
      >
        <Plus size={18} />
        <span>{t("sessions.new")}</span>
      </Button>
      <nav aria-label={t("navigation.main")}>
        {[
          { id: "home" as Page, label: t("navigation.home"), icon: Home },
          { id: "library" as Page, label: t("navigation.library"), icon: BookOpen },
          { id: "settings" as Page, label: t("navigation.settings"), icon: Settings },
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
      <div className="sidebar-scroll">
      {folderNavigation && !collapsed && <FolderNavigation {...folderNavigation} variant="sidebar"
        select={id => go(() => folderNavigation.select(id))}
        manage={() => go(folderNavigation.manage)} />}
      <div className="sidebar-label">
        {t("sessions.recent")}<span>{formatNumber(language, sessions.length)}</span>
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
                {formatDate(language, s.created_at)}
                {s.mode === "demo" ? t("sessions.demoSuffix") : ""}
              </small>
            </span>
          </button>
        ))}
        {!sessions.length && <p className="muted tiny">{t("sessions.empty")}</p>}
      </div>
      </div>
      <div className="private-card">
        <ShieldCheck size={18} />
        <div>
          {t("navigation.privateWorkspace")}<small>{t("navigation.privacy")}</small>
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
  const { t } = useI18n();
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
      title={t("navigation.workspace")}
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
  const { t } = useI18n();
  return (
    <header className="topbar">
      <div className="topbar-leading">
        <Button
          variant="ghost"
          size="icon"
          className="mobile-menu-toggle"
          data-dialog-fallback-focus
          aria-label={t("navigation.open")}
          aria-expanded={menuOpen}
          onClick={menu}
        >
          <Menu size={20} />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="desktop-menu-toggle"
          aria-label={t(collapsed ? "navigation.expand" : "navigation.collapse")}
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
          <span>{t("navigation.private")}</span>
          <ChevronRight size={14} />
          <strong title={title}>{title}</strong>
        </div>
      </div>
      <div className="topbar-actions">
        <LanguageSwitcher />
        <span
          className={cn("network-state", !online && "network-offline")}
          title={t("navigation.networkHint")}
        >
          {online ? <Wifi size={15} /> : <WifiOff size={15} />}
          <span>{t(online ? "navigation.online" : "navigation.offline")}</span>
        </span>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t(dark ? "navigation.light" : "navigation.dark")}
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
          title={t("navigation.logout")}
          aria-label={t("navigation.logout")}
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
  const { t } = useI18n();
  if (!message) return null;
  return (
    <div className="toast toast-enter" role="status">
      <AlertTriangle size={18} />
      <span>{message}</span>
      <Button variant="ghost" size="icon" aria-label={t("common.dismiss")} onClick={close}>
        <X size={16} />
      </Button>
    </div>
  );
}
