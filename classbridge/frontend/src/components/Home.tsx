import { translationLanguages, type TargetLanguage } from "../lib/translationLanguages";
import { useEffect, useState } from "react";
import { useASRProfiles } from "../lib/asrProfiles";
import { ASRSelector } from "./ASRModels";
import {
  ArrowRight,
  AudioLines,
  BookOpen,
  ChevronRight,
  Clock,
  FileText,
  GraduationCap,
  MessagesSquare,
  Mic,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Users,
  X,
  Settings2,
  Upload,
} from "lucide-react";
import { formatTime } from "../lib/api";
import { formatDate } from "../i18n";
import { safeDiagnostic } from "../i18n/errors";
import { useI18n } from "../i18n/I18nProvider";
import type { Mode, Session } from "../lib/types";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { Badge } from "./ui/badge";
import { Dialog } from "./ui/dialog";
import { FolderNavigation, type FolderNavigationProps } from "./SessionFolders";

export function Home({
  sessions,
  folderNavigation,
  moveSession,
  moveSessions,
  moving,
  search,
  setSearch,
  create,
  select,
  library,
  settings,
}: {
  sessions: Session[];
  folderNavigation?: FolderNavigationProps;
  moveSession?: (id: string, folderId: string) => Promise<void>;
  moveSessions?: (ids: string[], folderId: string) => Promise<boolean>;
  moving?: boolean;
  search: string;
  setSearch: (value: string) => void;
  create: (kind?: string) => void;
  select: (session: Session) => void;
  library: () => void;
  settings: () => void;
}) {
  const { t, language } = useI18n();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [destination, setDestination] = useState("");
  useEffect(() => { setSelectedIds([]); }, [search, folderNavigation?.selected]);
  const visibleIds = selectedIds.filter(id => sessions.some(session => session.id === id));
  const batchDisabled = moving || folderNavigation?.disabled;
  const total = sessions.reduce(
    (value, session) =>
      value + (session.captured_ms ?? session.duration_ms ?? 0),
    0,
  );
  const realCount = sessions.filter(
    (session) => session.mode === "real",
  ).length;
  return (
    <div className="home page-scroll">
      <div className="page-width">
        <div className="page-heading">
          <div>
            <span className="eyebrow">{t("navigation.home")}</span>
            <h1>{t("home.welcome")}</h1>
            <p>{t("home.intro")}</p>
          </div>
          <Button variant="secondary" onClick={library}>
            <Upload size={17} />
            {t("home.import")}
          </Button>
        </div>
        <section className="dashboard-actions" aria-label={t("home.types")}>
          {[
            {
              kind: "classroom",
              icon: GraduationCap,
              title: t("home.classroomNew"),
              text: t("home.classroomHint"),
            },
            {
              kind: "meeting",
              icon: Users,
              title: t("home.meetingNew"),
              text: t("home.meetingHint"),
            },
            {
              kind: "interview",
              icon: MessagesSquare,
              title: t("home.interviewNew"),
              text: t("home.interviewHint"),
            },
          ].map(({ kind, icon: Icon, title, text }) => (
            <button
              className="dashboard-action"
              key={kind}
              onClick={() => create(kind)}
            >
              <span className="quick-icon">
                <Icon size={22} />
              </span>
              <span>
                <strong>{title}</strong>
                <small>{text}</small>
              </span>
              <Plus size={17} />
            </button>
          ))}
        </section>
        <section className="stat-grid" aria-label={t("home.stats")}>
          <Card className="stat-card">
            <span>
              <FileText size={16} />
              {t(search ? "home.matches" : "home.loaded")}
            </span>
            <strong>
              {t("sessions.count", { count: sessions.length })}
            </strong>
            <p>{t("home.fromList")}</p>
          </Card>
          <Card className="stat-card">
            <span>
              <Clock size={16} />
              {t("home.duration")}
            </span>
            <strong>
              {Math.floor(total / 60000)}
              <small>{t("home.minutes")}</small>
            </strong>
            <p>{t(search ? "home.searchResults" : "home.currentList")} · {t("home.excludesPauses")}</p>
          </Card>
          <Card className="stat-card">
            <span>
              <Mic size={16} />
              {t("home.realSessions")}
            </span>
            <strong>
              {t("sessions.count", { count: realCount })}
            </strong>
            <p>{t("home.demoCount", { count: sessions.length - realCount })}</p>
          </Card>
        </section>
        <section className="recent-section" aria-label={t("home.history")}>
          {folderNavigation && <FolderNavigation {...folderNavigation} />}
          <div className="section-heading">
            <div>
              <h2>
                {folderNavigation?.selected === "unfiled" ? t("folders.unfiled") : folderNavigation?.folders.find(f => f.id === folderNavigation.selected)?.name || t("sessions.recent")} <span className="count-pill">{sessions.length}</span>
              </h2>
              <p>{t("home.openSaved")}</p>
            </div>
            <label className="search-field">
              <Search size={17} />
              <Input
                aria-label={t("home.search")}
                placeholder={t("home.searchPlaceholder")}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              {search && (
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={t("home.clearSearch")}
                  onClick={() => setSearch("")}
                >
                  <X size={14} />
                </Button>
              )}
            </label>
          </div>
          {folderNavigation && moveSessions && sessions.length > 0 && (
            <div className={`folder-batch-actions${visibleIds.length ? " has-selection" : ""}`} role="group" aria-label={t("home.batchMove")}>
              <label>
                <input type="checkbox" aria-label={t("home.select100")}
                  disabled={batchDisabled}
                  checked={visibleIds.length > 0 && sessions.slice(0, 100).every(s => visibleIds.includes(s.id))}
                  onChange={e => setSelectedIds(e.target.checked ? sessions.slice(0, 100).map(s => s.id) : [])} />
                {t("home.selectList")}
              </label>
              <span role="status">{visibleIds.length ? t("home.selected", { count: visibleIds.length }) : t("home.selectHint")}</span>
              {visibleIds.length > 0 && <>
              <select aria-label={t("home.destination")} value={destination} disabled={batchDisabled}
                onChange={e => setDestination(e.target.value)}>
                <option value="">{t("folders.unfiled")}</option>
                {folderNavigation.folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
              <Button disabled={batchDisabled || !visibleIds.length} onClick={async () => {
                if (await moveSessions(visibleIds, destination)) setSelectedIds([]);
              }}>{t("home.moveSelected")}</Button>
              <Button variant="ghost" disabled={batchDisabled} onClick={e => {
                e.currentTarget.closest('.folder-batch-actions')?.querySelector<HTMLInputElement>('input')?.focus();
                setSelectedIds([]);
              }}>{t("home.deselect")}</Button>
              </>}
            </div>
          )}
          {sessions.length ? (
            <div className="session-list">
              <div className="session-columns" aria-hidden="true">
                <span>{t("home.nameType")}</span>
                <span>{t("home.mode")}</span>
                <span>{t("home.status")}</span>
              </div>
              {sessions.map((session) => (
                <div key={session.id} className={`session-entry${visibleIds.includes(session.id) ? " is-selected" : ""}`}>
                {moveSessions && <label className="session-select">
                  <input type="checkbox" aria-label={t("home.selectSession", { title: session.title })}
                    checked={visibleIds.includes(session.id)}
                    disabled={batchDisabled || (!visibleIds.includes(session.id) && visibleIds.length >= 100)}
                    onChange={e => setSelectedIds(e.target.checked
                      ? [...visibleIds, session.id] : visibleIds.filter(id => id !== session.id))} />
                  <span className="sr-only">{t("home.select")}</span>
                </label>}
                <button
                  className="session-row"
                  onClick={() => select(session)}
                >
                  <span className="session-symbol">
                    {session.kind === "meeting" ? (
                      <Users size={20} />
                    ) : session.kind === "interview" ? (
                      <MessagesSquare size={20} />
                    ) : (
                      <GraduationCap size={20} />
                    )}
                  </span>
                  <span className="session-title">
                    <strong>{session.title}</strong>
                    <small>
                      {formatDate(language, session.created_at)}
                      <span>·</span>
                      <Clock size={12} />
                      {formatTime(session.captured_ms ?? session.duration_ms)}
                      <span>·</span>
                      {t(session.kind === "meeting" ? "home.meeting" : session.kind === "interview" ? "home.interview" : "home.classroom")}
                    </small>
                  </span>
                  <Badge className={session.mode === "demo" ? "amber" : "blue"}>
                    {t(session.mode === "demo" ? "home.demo" : "home.real")}
                  </Badge>
                  <span className="row-state">
                    {(
                      {
                        recording: t("home.recording"),
                        stopped: t("home.stopped"),
                        idle: t("home.idle"),
                        completed: t("home.completed"),
                        processing: t("home.processing"),
                        failed: t("home.failed"),
                      } as Record<string, string>
                    )[session.status] || session.status}
                  </span>
                  <ChevronRight size={16} />
                </button>
                {folderNavigation && moveSession && <details className="session-row-tools"
                  onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) e.currentTarget.open = false; }}
                  onKeyDown={e => { if (e.key === "Escape") { e.preventDefault(); e.currentTarget.open = false; e.currentTarget.querySelector("summary")?.focus(); } }}>
                  <summary aria-label={t("home.actionsTitle", { title: session.title })} title={t("home.actions")}><span aria-hidden="true">•••</span></summary>
                  <label className="session-move">
                  {t("home.moveTo")}
                  <select aria-label={t("home.moveSession", { title: session.title })}
                    value={session.folder_id || ""}
                    disabled={moving || folderNavigation.disabled}
                    onChange={e => void moveSession(session.id, e.target.value)}>
                    <option value="">{t("folders.unfiled")}</option>
                    {folderNavigation.folders.map(folder =>
                      <option key={folder.id} value={folder.id}>{folder.name}</option>)}
                  </select>
                </label></details>}
                </div>
              ))}
            </div>
          ) : (
            <Card className="empty-state">
              <FileText size={28} />
              <h3>{t(search ? "home.noMatches" : folderNavigation?.selected ? "home.emptyCategory" : "home.empty")}</h3>
              <p>
                {t(search ? "home.noMatchesHint" : "home.demoHint")}
              </p>
              {!search && (
                <Button onClick={() => create()}>
                  <Plus size={16} />
                  {t("home.create")}
                </Button>
              )}
            </Card>
          )}
        </section>
        <div className="dashboard-links">
          <Button variant="secondary" onClick={library}>
            <BookOpen size={16} />
            {t("home.library")}
            <ArrowRight size={15} />
          </Button>
          <Button variant="ghost" onClick={settings}>
            <Settings2 size={16} />
            {t("home.preferences")}
          </Button>
        </div>
        <footer className="page-footer">
          <span>
            <ShieldCheck size={14} />
            {t("home.private")}
          </span>
          <span>ClassBridge</span>
        </footer>
      </div>
    </div>
  );
}
export function NewSession({
  kind: initial,
  close,
  submit,
  defaultRetain = false,
  defaultTarget = "zh-CN",
  retention = 7,
}: {
  kind: string;
  close: () => void;
  submit: (data: {
    title: string;
    kind: string;
    mode: Mode;
    retain_audio: boolean;
    target_language: TargetLanguage;
    asr_profile_id?: string;
  }) => Promise<void>;
  defaultRetain?: boolean;
  defaultTarget?: TargetLanguage;
  retention?: number;
}) {
  const { t } = useI18n();
  const [kind, setKind] = useState(initial),
    [title, setTitle] = useState(""),
    [mode, setMode] = useState<Mode>("demo"),
    [retain, setRetain] = useState(defaultRetain),
    [target, setTarget] = useState<TargetLanguage>(defaultTarget),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [errorDetail, setErrorDetail] = useState("");
  const {profiles}=useASRProfiles();
  const [asrProfile,setASRProfile]=useState("");
  useEffect(()=>{if(!asrProfile){const profile=profiles.find(p=>p.is_default && p.enabled && p.validation.valid);if(profile)setASRProfile(profile.id);}},[profiles,asrProfile]);
  return (
    <Dialog
      title={t("sessions.new")}
      description={t("newSession.description")}
      close={close}
      busy={busy}
    >
      <div className="modal-title">
        <span className="quick-icon purple">
          <AudioLines size={23} />
        </span>
        <button
          className="icon-button"
          aria-label={t("newSession.close")}
          disabled={busy}
          onClick={close}
        >
          <X size={20} />
        </button>
      </div>
      <h2 aria-hidden="true">{t("sessions.new")}</h2>
      <p className="muted">{t("newSession.hint")}</p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy) return;
          if (mode === "demo" && target !== "zh-CN") { setError("demo"); return; }
          if (mode === "real" && !profiles.some(p=>p.id===asrProfile && p.enabled && p.validation.valid)) {setError("model");return;}
          setBusy(true);
          setError("");
          setErrorDetail("");
          try {
            await submit({
              title:
                title.trim() ||
                `${kind === "meeting" ? "会议" : kind === "interview" ? "访谈" : "课堂"} · ${new Date().toLocaleDateString("zh-CN")}`,
              kind,
              mode,
              retain_audio: retain,
              target_language: target,
              ...(mode==="real"?{asr_profile_id:asrProfile}:{}),
            });
          } catch (err) {
            setError("failed");
            setErrorDetail(safeDiagnostic(err instanceof Error ? err.message : ""));
            setBusy(false);
          }
        }}
      >
        <fieldset disabled={busy} className="new-session-fields">
          {mode==="real" && <ASRSelector value={asrProfile} onChange={setASRProfile} disabled={busy}/>}
          <div className="segmented">
            {[
              ["classroom", t("home.classroom")],
              ["meeting", t("home.meeting")],
              ["interview", t("home.interview")],
            ].map(([k, t]) => (
              <button
                type="button"
                key={k}
                className={kind === k ? "active" : ""}
                onClick={() => setKind(k)}
              >
                {t}
              </button>
            ))}
          </div>
          <label>
            {t("newSession.name")}
            <Input
              autoFocus
              maxLength={160}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("newSession.placeholder")}
            />
          </label>
          <div className="mode-choices">
            <button
              type="button"
              className={mode === "demo" ? "mode-choice chosen" : "mode-choice"}
              onClick={() => setMode("demo")}
            >
              <Sparkles size={20} />
              <strong>{t("home.demo")}</strong>
              <small>
                {t("newSession.noPaid")}
                <br />
                {t("newSession.noMic")}
              </small>
            </button>
            <button
              type="button"
              className={mode === "real" ? "mode-choice chosen" : "mode-choice"}
              onClick={() => setMode("real")}
            >
              <Mic size={20} />
              <strong>{t("newSession.real")}</strong>
              <small>
                {t("newSession.mic")}
                <br />
                {t("newSession.keys")}
              </small>
            </button>
          </div>
          <label>
            {t("newSession.target")}
            <select aria-label={t("newSession.target")} value={target} onChange={e=>setTarget(e.target.value as TargetLanguage)}>
              {Object.entries(translationLanguages).map(([code,language])=><option key={code} value={code}>{language.label}</option>)}
            </select>
            <small>{t("newSession.fixed")}</small>
          </label>
          {mode === "demo" && <p role="status">{t("newSession.demoHint")}</p>}
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={retain}
              disabled={mode === "demo"}
              onChange={(e) => setRetain(e.target.checked)}
            />
            <span>
              {t("newSession.retain")}
              <small>
                {mode === "demo"
                  ? t("newSession.noAudio")
                  : t("newSession.retention", { days: retention })}
              </small>
            </span>
          </label>
        </fieldset>
        {error && (
          <div className="error-box" role="alert">
            {t(error === "demo" ? "newSession.demoError" : error === "model" ? "newSession.modelError" : "newSession.failed")}
            {error === "failed" && errorDetail && <details><summary>{t("newSession.details")}</summary>{errorDetail}</details>}
          </div>
        )}
        <Button type="submit" className="full" disabled={busy || (mode === "demo" && target !== "zh-CN")}>
          {t(busy ? "newSession.busy" : "home.create")}
          <ArrowRight size={17} />
        </Button>
      </form>
    </Dialog>
  );
}
