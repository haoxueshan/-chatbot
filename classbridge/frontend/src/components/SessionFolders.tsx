import { useState } from "react";
import type { SessionFolder } from "../lib/types";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Dialog } from "./ui/dialog";

export interface FolderNavigationProps {
  folders: SessionFolder[];
  selected: string;
  select: (id: string) => void;
  manage: () => void;
  disabled?: boolean;
}

export function FolderNavigation({ folders, selected, select, manage, disabled }: FolderNavigationProps) {
  return <div className="folder-navigation">
    <label>会话分类
      <select aria-label="会话分类" value={selected} disabled={disabled}
        onChange={e => select(e.target.value)}>
        <option value="">全部会话</option>
        <option value="unfiled">未分类</option>
        {folders.map(folder => <option key={folder.id} value={folder.id}>
          {folder.name} ({folder.session_count})
        </option>)}
      </select>
    </label>
    <Button variant="ghost" disabled={disabled} onClick={manage}>管理文件夹</Button>
  </div>;
}

export function FolderManager({ folders, close, save, remove }: {
  folders: SessionFolder[];
  close: () => void;
  save: (id: string | null, name: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [deleting, setDeleting] = useState<SessionFolder | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
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
      setError(e instanceof Error ? e.message : "操作失败，请重试");
    } finally { setBusy(false); }
  }
  return <Dialog title="管理文件夹" close={close} busy={busy}>
    <h2>管理文件夹</h2>
    <p>文件夹仅用于私人会话分类，不移动或删除音频、字幕及资料。</p>
    <form onSubmit={e => { e.preventDefault(); void perform(() => save(editing, name)); }}>
      <label>{editing ? "重命名文件夹" : "新建文件夹"}
        <Input aria-label="文件夹名称" value={name} maxLength={80} disabled={busy}
          onChange={e => setName(e.target.value)} />
      </label>
      <Button type="submit" disabled={busy || !name.trim()}>{editing ? "保存名称" : "创建文件夹"}</Button>
      {editing && <Button type="button" variant="ghost" disabled={busy}
        onClick={() => { setEditing(null); setName(""); }}>取消重命名</Button>}
    </form>
    <ul>
      {folders.map(folder => <li key={folder.id}>
        <span>{folder.name} · {folder.session_count} 个会话</span>
        <Button variant="ghost" disabled={busy} onClick={() => {
          setEditing(folder.id); setName(folder.name); setDeleting(null);
        }}>重命名</Button>
        <Button variant="ghost" disabled={busy} onClick={() => setDeleting(folder)}>删除</Button>
      </li>)}
    </ul>
    {!folders.length && <p>暂无文件夹。</p>}
    {deleting && <div role="alert">
      <p>删除“{deleting.name}”？其中的会话将恢复为未分类，内容不会删除。</p>
      <Button disabled={busy} onClick={() => void perform(() => remove(deleting.id))}>确认删除文件夹</Button>
      <Button variant="ghost" disabled={busy} onClick={() => setDeleting(null)}>取消</Button>
    </div>}
    {error && <p role="alert">{error}</p>}
    <Button variant="secondary" disabled={busy} onClick={close}>关闭</Button>
  </Dialog>;
}