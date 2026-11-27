import { useId, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Folder, FolderOpen, Folders, Settings2 } from "lucide-react";
import type { SessionFolder } from "../lib/types";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Dialog } from "./ui/dialog";
import { useI18n } from "../i18n/I18nProvider";

export interface FolderNavigationProps {
  folders: SessionFolder[];
  selected: string;
  select: (id: string) => void;
  manage: () => void;
  disabled?: boolean;
}

export function FolderNavigation({ folders, selected, select, manage, disabled, variant = "select" }: FolderNavigationProps & { variant?: "select" | "sidebar" }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(true);
  const listId = useId();
  if (variant === "sidebar") return <nav className="folder-sidebar" aria-label={t("folders.title")}>
    <div className="folder-sidebar-heading">
      <button aria-label={t(expanded ? "folders.collapse" : "folders.expand")} aria-expanded={expanded}
        aria-controls={listId} onClick={() => setExpanded(!expanded)}>
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}{t("folders.label")}
      </button>
      <Button variant="ghost" size="icon" aria-label={t("folders.manage")} title={t("folders.manage")} disabled={disabled} onClick={manage}><Settings2 size={16} /></Button>
    </div>
    <div id={listId} hidden={!expanded} className="folder-sidebar-list">
      {[{id:"",name:t("folders.all")},{id:"unfiled",name:t("folders.unfiled")},...folders].map(folder => (
        <button key={folder.id} className={`folder-link${selected === folder.id ? " selected" : ""}`}
          aria-label={folder.name} aria-current={selected === folder.id ? "true" : undefined}
          title={folder.name} disabled={disabled} onClick={() => select(folder.id)}>
          {folder.id === "" ? <Folders size={16} /> : selected === folder.id ? <FolderOpen size={16} /> : <Folder size={16} />}
          <span>{folder.name}</span>{"session_count" in folder && <small>{folder.session_count}</small>}
        </button>
      ))}
      {!folders.length && <p className="muted tiny">{t("folders.hint")}</p>}
    </div>
    {!expanded && <p className="folder-context" title={folders.find(f => f.id === selected)?.name}>
      {selected === "unfiled" ? t("folders.unfiled") : folders.find(f => f.id === selected)?.name || t("folders.all")}
    </p>}
  </nav>;
  return <div className="folder-navigation">
    <label>{t("folders.category")}
      <select aria-label={t("folders.category")} value={selected} disabled={disabled}
        onChange={e => select(e.target.value)}>
        <option value="">{t("folders.all")}</option>
        <option value="unfiled">{t("folders.unfiled")}</option>
        {folders.map(folder => <option key={folder.id} value={folder.id}>
          {folder.name} ({folder.session_count})
        </option>)}
      </select>
    </label>
    <Button variant="ghost" disabled={disabled} onClick={manage}>{t("folders.manage")}</Button>
  </div>;
}

export function FolderManager({ folders, close, save, remove }: {
  folders: SessionFolder[];
  close: () => void;
  save: (id: string | null, name: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [deleting, setDeleting] = useState<SessionFolder | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const nameInput = useRef<HTMLInputElement>(null);
  async function perform(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await action();
      setEditing(null);
      setName("");
      setDeleting(null);
    } catch (e) {
      setError(deleting ? "deleteFailed" : "failed");
    } finally { setBusy(false); }
  }
  return <Dialog title={t("folders.manage")} close={close} busy={busy} className="folder-manager">
    <h2>{t("folders.manage")}</h2>
    <p>{t("folders.description")}</p>
    <form onSubmit={e => { e.preventDefault(); void perform(() => save(editing, name)); }}>
      <label>{t(editing ? "folders.rename" : "folders.new")}
        <Input ref={nameInput} aria-label={t("folders.name")} value={name} maxLength={80} disabled={busy}
          onChange={e => setName(e.target.value)} />
      </label>
      <Button type="submit" disabled={busy || !name.trim()}>{t(editing ? "folders.saveName" : "folders.create")}</Button>
      {editing && <Button type="button" variant="ghost" disabled={busy}
        onClick={() => { setEditing(null); setName(""); }}>{t("folders.cancelRename")}</Button>}
    </form>
    <ul className="folder-manager-list">
      {folders.map(folder => <li key={folder.id}>
        <span title={folder.name}><strong>{folder.name}</strong><small>{t("sessions.count", { count: folder.session_count })}</small></span>
        <Button variant="ghost" disabled={busy} onClick={() => {
          setEditing(folder.id); setName(folder.name); setDeleting(null); nameInput.current?.focus();
        }}>{t("folders.renameAction")}</Button>
        <Button variant="ghost" disabled={busy} onClick={() => setDeleting(folder)}>{t("folders.delete")}</Button>
      </li>)}
    </ul>
    {!folders.length && <p>{t("folders.empty")}</p>}
    {deleting && <div role="alert" className="error-box">
      <p>{t("folders.confirmText", { name: deleting.name })}</p>
      <Button disabled={busy} onClick={() => void perform(() => remove(deleting.id))}>{t("folders.confirm")}</Button>
      <Button variant="ghost" disabled={busy} onClick={() => setDeleting(null)}>{t("folders.cancel")}</Button>
    </div>}
    {error && <p role="alert" className="error-box">{t(error === "deleteFailed" ? "folders.deleteFailed" : "common.error")}</p>}
    <Button variant="secondary" disabled={busy} onClick={close}>{t("folders.close")}</Button>
  </Dialog>;
}
