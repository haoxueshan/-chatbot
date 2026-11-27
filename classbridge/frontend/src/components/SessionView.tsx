import { translationLanguageLabel, translationDirection } from "../lib/translationLanguages";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown,
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  Download,
  Expand,
  Eye,
  EyeOff,
  FileText,
  Focus,
  Languages,
  LoaderCircle,
  MessageSquare,
  Mic,
  PanelRightClose,
  PanelRightOpen,
  RefreshCw,
  Sparkles,
  Square,
  Trash2,
  Volume2,
  Wifi,
  X,
} from "lucide-react";
import { formatTime, post, request } from "../lib/api";
import { formatDate } from "../i18n";
import { useLive } from "../lib/useLive";
import { buildTimeline, incidentCode } from "../lib/timeline";
import { recognitionStatusCode } from "../lib/captureHealth";
import type { Citation, Preferences, Session, Stage } from "../lib/types";
import { Chat } from "./Chat";
import { DocumentPreview, Library } from "./Library";
import { Dialog } from "./ui/dialog";
import { ASRSelector } from "./ASRModels";
import { useI18n } from "../i18n/I18nProvider";

function sourceReferences(
  item: unknown,
): { sentence_id: string; source_revision: number }[] {
  if (!item || typeof item !== "object") return [];
  const value = (item as Record<string, unknown>).sources;
  if (!Array.isArray(value)) return [];
  return value.filter(
    (source): source is { sentence_id: string; source_revision: number } =>
      source != null &&
      typeof source.sentence_id === "string" &&
      typeof source.source_revision === "number",
  );
}
function readable(item: unknown, labels: { owner: string; date: string; pending: string }): string {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return "";
  const v = item as Record<string, unknown>;
  const text = String(
    v.text ||
      v.summary ||
      v.description ||
      v.term ||
      v.title ||
      v.topic ||
      v.content ||
      "",
  );
  const meaning = v.definition || v.meaning;
  return `${text}${meaning ? `: ${meaning}` : ""}${v.owner ? ` · ${labels.owner}: ${v.owner}` : ""}${v.due_original ? ` · ${labels.date}: ${v.due_original} (${v.due_basis || labels.pending})` : ""}`;
}
function StagePanel({
  stages,
  generate,
  busy,
  jump,
}: {
  stages: Stage[];
  generate: () => void;
  busy: boolean;
  jump: (id: string, revision?: number) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="stage-panel">
      <div className="panel-intro">
        <span className="eyebrow">{t("stage.eyebrow")}</span>
        <p>{t("stage.intro")}</p>
        <button className="secondary full" disabled={busy} onClick={generate}>
          {busy ? (
            <LoaderCircle size={15} className="spin" />
          ) : (
            <RefreshCw size={15} />
          )}
          {t("stage.generate")}
        </button>
      </div>
      {stages.length ? (
        stages.map((s, index) => (
          <article className="stage-card" key={s.id}>
            <div className="stage-number">
              <span>{String(index + 1).padStart(2, "0")}</span>
              <small>{t("stage.highlights")}</small>
            </div>
            <h3>{s.topic && !/^(none|null|undefined)$/i.test(s.topic.trim()) ? s.topic : t("stage.number", { count: index + 1 })}</h3>
            <p>{s.summary}</p>
            {s.superseded && <p className="info-box">{t("stage.historical")}</p>}
            {[
              [t("stage.knowledge"), s.knowledge_points],
              [t("stage.terms"), s.terms],
              [t("stage.decisions"), s.decisions],
              [t("stage.actions"), s.action_items],
            ].map(
              ([label, items]) =>
                Array.isArray(items) &&
                !!items.length && (
                  <div className="stage-items" key={String(label)}>
                    <h4>{String(label)}</h4>
                    <ul>
                      {items.map((v, i) => (
                        <li key={i}>
                          {readable(v, { owner: t("stage.owner"), date: t("stage.originalDate"), pending: t("stage.unconfirmed") })}
                          {sourceReferences(v).length > 0 && (
                            <div className="source-chips">
                              {sourceReferences(v).map(
                                (source: {
                                  sentence_id: string;
                                  source_revision: number;
                                }) => (
                                  <button
                                    key={`${source.sentence_id}:${source.source_revision}`}
                                    onClick={() =>
                                      jump(
                                        source.sentence_id,
                                        source.source_revision,
                                      )
                                    }
                                  >
                                    <BookOpen size={11} /> {t("stage.original")} v
                                    {source.source_revision}
                                  </button>
                                ),
                              )}
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                ),
            )}
            {!!s.source_sentence_ids?.length && (
              <div className="source-chips">
                {s.source_sentence_ids.map((id, i) => (
                  <button
                    onClick={() =>
                      jump(
                        id,
                        s.sources?.find((source) => source.sentence_id === id)
                          ?.source_revision,
                      )
                    }
                    key={id}
                  >
                    <BookOpen size={11} />
                    {t("stage.source", { count: i + 1 })}
                  </button>
                ))}
              </div>
            )}
          </article>
        ))
      ) : (
        <div className="empty-state compact">
          <Sparkles size={29} />
          <h3>{t("stage.empty")}</h3>
          <p>{t("stage.emptyHint")}</p>
        </div>
      )}
      <div className="panel-footnote">
        {t("stage.footnote")}
      </div>
    </div>
  );
}

export function SessionView({
  session,
  preferences,
  onActivity,
  refresh,
  back,
  notify,
  openSession,
  deleted,
}: {
  session: Session;
  preferences: Preferences;
  onActivity: (active: boolean) => void;
  refresh: () => void;
  back: () => void;
  notify: (m: string) => void;
  openSession: (id: string) => void;
  deleted: () => void;
}) {
  const { t, language } = useI18n();
  const [microphoneId, setMicrophoneId] = useState(() => {
    try { return typeof window === "undefined" ? "" : window.localStorage.getItem("classbridge.microphone.v1") || ""; }
    catch { return ""; }
  });
  const [microphones, setMicrophones] = useState<{ deviceId: string; label: string }[]>([]);
  const [deviceError,setDeviceError]=useState<"" | "sessionDetails.devicesUnsupported" | "sessionDetails.devicesFailed">("");
  const [modelBusy,setModelBusy]=useState(false),[selectedModel,setSelectedModel]=useState(session.asr_profile_id || "");
  useEffect(()=>setSelectedModel(session.asr_profile_id || ""),[session.id,session.asr_profile_id]);
  const deviceGeneration=useRef(0);
  const devicesMounted=useRef(true);
  const live = useLive(session, refresh, {
    deviceId: microphoneId,
    processingMode: preferences.audio_processing_mode || "standard",
  }, preferences.audio_runtime);
  const refreshMicrophones = () => {
    const generation=++deviceGeneration.current;
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) {
      setDeviceError("sessionDetails.devicesUnsupported");return;
    }
    void navigator.mediaDevices.enumerateDevices().then((items) => {
      if(!devicesMounted.current || generation!==deviceGeneration.current)return;
      setMicrophones(items.filter((item) => item.kind === "audioinput" && item.deviceId)
        .map((item) => ({ deviceId: item.deviceId, label: item.label })));
      setDeviceError("");
    }).catch(() => {if(devicesMounted.current && generation===deviceGeneration.current)setDeviceError("sessionDetails.devicesFailed");});
  };
  useEffect(() => {
    if (session.mode !== "real" || typeof navigator === "undefined") return;
    devicesMounted.current=true;
    refreshMicrophones();
    navigator.mediaDevices?.addEventListener?.("devicechange", refreshMicrophones);
    return () => {devicesMounted.current=false;deviceGeneration.current++;navigator.mediaDevices?.removeEventListener?.("devicechange", refreshMicrophones);};
  }, [session.mode]);
  useEffect(()=>{if(session.mode==="real" && live.active)refreshMicrophones();},[live.preparing,live.active]);
  const chooseMicrophone = (id: string) => {
    if(live.active || live.settling)return;
    setMicrophoneId(id);
    try { window.localStorage.setItem("classbridge.microphone.v1", id); }
    catch { /* private mode/storage restrictions */ }
  };
  const timeline = useMemo(() => buildTimeline(live.segments, live.gaps), [live.segments, live.gaps]);
  const [tab, setTab] = useState<"subtitles" | "summary" | "chat">("subtitles"),
    [sideTab, setSideTab] = useState<"summary" | "chat">("summary"),
    [sidebar, setSidebar] = useState(true),
    [showOriginal, setShowOriginal] = useState(preferences.show_original),
    [focus, setFocus] = useState(false),
    [following, setFollowing] = useState(true),
    [selectedSource, setSelectedSource] = useState<Citation | null>(null),
    [busy, setBusy] = useState(false),
    [exporting, setExporting] = useState(false),
    [exportBusy, setExportBusy] = useState(false),
    [documentsOpen, setDocumentsOpen] = useState(false);
  const list = useRef<HTMLDivElement>(null),
    end = useRef<HTMLDivElement>(null);
  const followingRef = useRef(following);
  followingRef.current = following;
  useEffect(() => {
    onActivity(live.active || live.settling);
    return () => onActivity(false);
  }, [live.active, live.settling, onActivity]);
  useEffect(() => {
    const el = list.current;
    if (!following || !el) return;
    let frame: number | undefined;
    const schedule = () => {
      if (frame !== undefined) return;
      frame = window.requestAnimationFrame(() => {
        frame = undefined;
        if (!followingRef.current) return;
        const bottom = Math.max(0, el.scrollHeight - el.clientHeight);
        if (Math.abs(bottom - el.scrollTop) > 1) el.scrollTo({ top: bottom, behavior: "auto" });
      });
    };
    schedule();
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(schedule);
    observer?.observe(el);
    const latest = end.current?.previousElementSibling;
    if (latest) observer?.observe(latest);
    return () => { observer?.disconnect(); if (frame !== undefined) window.cancelAnimationFrame(frame); };
  }, [timeline, following, showOriginal, tab]);
  useEffect(() => {
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);
  const jump = (sentenceId: string) => {
    setTab("subtitles");
    setFollowing(false);
    setTimeout(() => {
      const target = document.getElementById(`sentence-${sentenceId}`);
      target?.scrollIntoView({ behavior: "smooth", block: "center" });
      target?.classList.add("highlight-source");
      setTimeout(() => target?.classList.remove("highlight-source"), 5000);
    }, 80);
  };
  const citation = (c: Citation) => {
    setSelectedSource(c);
    if (
      c.kind === "sentence" &&
      (!c.session_id || c.session_id === session.id) &&
      c.sentence_id
    )
      jump(c.sentence_id);
  };
  const jumpEvidence = async (id: string, revision?: number) => {
    jump(id);
    if (revision) {
      try {
        const versions = await request<
          { text: string; source_revision: number }[]
        >(`/sessions/${session.id}/versions/${encodeURIComponent(id)}`);
        const source = versions.find((v) => v.source_revision === revision);
        if (source)
          setSelectedSource({
            id,
            kind: "sentence",
            sentence_id: id,
            session_id: session.id,
            source_revision: revision,
            quote: source.text,
          });
      } catch (e) {
        notify(t("common.error"));
      }
    }
  };
  const summarize = async () => {
    setBusy(true);
    try {
      await post(`/sessions/${session.id}/summarize`);
      notify(t("sessionDetails.summaryQueued"));
      refresh();
    } catch (e) {
      notify(t("common.error"));
    } finally {
      setBusy(false);
    }
  };
  const audioAvailable =
    ["available", "ready", "saved"].includes(session.audio_status || "") ||
    !!session.audio_assets?.length;
  const downloadReport = async (format: string) => {
    setExporting(false);
    setExportBusy(true);
    try {
      const job = await post<{ task_id: string }>(
        `/sessions/${session.id}/exports`,
        { format },
      );
      notify(t("sessionDetails.exportQueued"));
      for (let i = 0; i < 60; i++) {
        const state = await request<{
          status: string;
          error?: string;
          download_url?: string;
        }>(`/sessions/${session.id}/exports/${job.task_id}`);
        if (state.status === "completed" && state.download_url) {
          const a = document.createElement("a");
          a.href = state.download_url;
          a.download = "";
          a.click();
          notify(t("sessionDetails.exportReady"));
          return;
        }
        if (state.status === "failed")
          throw new Error("export_failed");
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      notify(t("sessionDetails.exportPending"));
      refresh();
    } catch (e) {
      notify(t("common.error"));
    } finally {
      setExportBusy(false);
    }
  };
  const target = session.target_language || "zh-CN";
  const targetLabel = translationLanguageLabel(target);
  return (
    <div className={`session-view ${focus ? "focus-mode" : ""}`}>
      <div className="session-heading">
        <div className="session-title-group">
          <h1 title={session.title}>{session.title}</h1>
          <div className="session-reading-meta">
            <span className={`badge ${session.mode === "demo" ? "amber" : "blue"}`}>
              {t(session.mode === "demo" ? "sessionTools.demo" : "sessionTools.real")}
            </span>
            <span>
              <Languages size={13} />
              {targetLabel}
            </span>
          </div>
        </div>
        <details
          className="session-details"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.currentTarget.open = false;
              event.currentTarget.querySelector("summary")?.focus();
            }
          }}
        >
          <summary aria-label={t("sessionTools.details")} title={t("sessionTools.details")}>
            <ChevronDown size={18} />
            <span>{t("sessionTools.tools")}</span>
          </summary>
          <div className="session-details-content">
            {session.mode==="real" && <ASRSelector value={selectedModel} historical={session.asr_snapshot?.display_name}
              disabled={live.active || live.settling || modelBusy || ["preparing","recording","processing"].includes(session.status)}
              onChange={id=>{setModelBusy(true);void request(`/sessions/${session.id}/asr-profile`,{method:"PATCH",body:JSON.stringify({asr_profile_id:id})})
                .then(()=>{setSelectedModel(id);refresh();}).catch(e=>notify(e.message)).finally(()=>setModelBusy(false));}}/>}
            {session.asr_streams?.length ? <details><summary>{t("sessionDetails.history")}</summary>{session.asr_streams.map(s=><p key={s.stream_id} className="tiny muted">{formatTime(s.offset_ms)} · {s.snapshot?.provider || t("sessionDetails.legacy")} / {s.snapshot?.model_id || t("sessionDetails.unknownModel")}{s.snapshot?.provenance==="legacy_environment_assumed"?t("sessionDetails.assumed"):""}</p>)}</details> : null}
            <p className="session-full-title">{session.title}</p>
            <button
              className="back-link"
              onClick={back}
              disabled={live.active || live.settling}
            >
              <ChevronLeft size={14} />
              {t("sessionTools.all")}
            </button>
            <div className="session-meta">
              <span>{formatDate(language, session.created_at)}</span>
              <span>·</span>
              <span>
                <Languages size={13} />
                {session.mode === "demo"
                  ? t("sessionDetails.demoHint", { target: targetLabel })
                  : live.active
                    ? t("sessionDetails.currentHint", { hint: live.preparing ? t("sessionDetails.waiting") : live.effectiveASR?.hints === undefined ? t("settings.unreported") : live.effectiveASR.hints.length ? live.effectiveASR.hints.join(" / ") : t("settings.asrAuto"), target: targetLabel })
                    : t("sessionDetails.nextHint", { hint: t(preferences.asr_language_mode === "ko" ? "settings.asrKo" : preferences.asr_language_mode === "ko_en" ? "settings.asrKoEn" : "settings.asrAuto"), target: targetLabel })}
              </span>
              {live.active && live.effectiveASR?.model && (
                <span>{t("sessionDetails.currentModel")} {live.effectiveASR.provider} / {live.effectiveASR.model}</span>
              )}
              {live.active && live.translationTarget && (
                <span>
                  {t("sessionDetails.serverTarget")} {translationLanguageLabel(live.translationTarget)}
                </span>
              )}
              <span
                className={`badge ${session.mode === "demo" ? "amber" : "blue"}`}
              >
                {t(session.mode === "demo" ? "sessionTools.demo" : "sessionTools.real")}
              </span>
            </div>
            <div className="session-tools">
              <button
                className="icon-button"
                title={t("sessionTools.documents")}
                aria-label={t("sessionTools.documents")}
                disabled={live.active || live.settling}
                onClick={() => setDocumentsOpen(true)}
              >
                <BookOpen size={17} />
              </button>
              <button
                className="icon-button danger"
                title={t("sessionTools.delete")}
                aria-label={t("sessionTools.delete")}
                disabled={live.active || live.settling}
                onClick={async () => {
                  if (
                    confirm(
                      t("sessionTools.deleteConfirm"),
                    )
                  ) {
                    try {
                      await request(`/sessions/${session.id}`, {
                        method: "DELETE",
                      });
                      deleted();
                    } catch (e) {
                      notify(t("common.error"));
                    }
                  }
                }}
              >
                <Trash2 size={17} />
              </button>
              <div className="dropdown">
                <button
                  className="secondary"
                  disabled={exportBusy}
                  onClick={() => setExporting(!exporting)}
                >
                  <Download size={15} />
                  <span>{t(exportBusy ? "sessionTools.exporting" : "sessionTools.export")}</span>
                  <ChevronDown size={13} />
                </button>
                {exporting && (
                  <div className="dropdown-menu">
                    {[
                      ["md", "Markdown"],
                      ["txt", t("sessionTools.txt")],
                      ["pdf", t("sessionTools.pdf")],
                    ].map(([value, label]) => (
                      <a
                        key={value}
                        download
                        href={`/api/sessions/${session.id}/export?format=${value}`}
                        onClick={(event) => {
                          event.preventDefault();
                          void downloadReport(value);
                        }}
                      >
                        {label}
                      </a>
                    ))}
                  </div>
                )}
              </div>
              <button
                className="icon-button"
                title={t(focus ? "sessionTools.exitFocus" : "sessionTools.focus")}
                aria-label={t("sessionTools.toggleFocus")}
                onClick={() => setFocus(!focus)}
              >
                {focus ? <Expand size={18} /> : <Focus size={18} />}
              </button>
              <button
                className="icon-button desktop-side-toggle"
                title={t(sidebar ? "sessionTools.collapse" : "sessionTools.expand")}
                aria-label={t("sessionTools.toggleSidebar")}
                onClick={() => setSidebar(!sidebar)}
              >
                {sidebar ? (
                  <PanelRightClose size={18} />
                ) : (
                  <PanelRightOpen size={18} />
                )}
              </button>
            </div>
            <div
              className={`mode-banner ${session.mode === "demo" ? "demo" : "real"}`}
            >
              <span>
                {session.mode === "demo" ? (
                  <Sparkles size={15} />
                ) : (
                  <Mic size={15} />
                )}
                <strong>
                  {session.mode === "demo"
                    ? t("sessionExtra.demo")
                    : t("sessionExtra.real")}
                </strong>
                {live.active && !live.preparing && live.translationTarget && (
                  <small>
                    {t("sessionDetails.translation")} {translationLanguageLabel(live.translationTarget)}
                  </small>
                )}
                {session.mode === "real" &&
                  live.active &&
                  !live.preparing &&
                  live.asrEnhancement && (
                    <small>
                      {t("sessionDetails.enhancement", { count: live.asrEnhancement.hotword_count, chars: live.asrEnhancement.context_chars })}
                    </small>
                  )}
                <span>
                  {t(session.mode === "demo" ? "sessionDetails.demoNotice" : "sessionDetails.foreground")}
                </span>
              </span>
              <span className="saved-indicator">
                <Check size={14} />
                {t("sessionTools.saved")}
              </span>
            </div>
            <div className="subtitle-footer">
              <span>
                <Check size={13} />
                {t("sessionTools.restore")}
              </span>
              <div>
                <button
                  className="text-button"
                  disabled={live.active || live.settling || !live.segments.length}
                  onClick={async () => {
                    if (
                      confirm(t("sessionTools.clearConfirm"))
                    ) {
                      try {
                        const result = await request<{ event_seq?: number }>(
                          `/sessions/${session.id}/segments`,
                          {
                            method: "DELETE",
                          },
                        );
                        live.clear(result.event_seq);
                        refresh();
                      } catch (e) {
                        notify(t("common.error"));
                      }
                    }
                  }}
                >
                  <Trash2 size={13} />
                  {t("sessionTools.clear")}
                </button>
              </div>
            </div>
            {session.mode === "real" && (
              <details className="microphone-options">
                <summary>
                  {t("sessionDetails.microphone")} ·{" "}
                  {t(live.asrAcousticProfile === "near" ? "sessionDetails.near" : live.asrAcousticProfile === "far" ? "sessionDetails.far" : "sessionDetails.waiting")}
                </summary>
                <div className="microphone-controls">
                  <label htmlFor="classbridge-microphone">{t("sessionTools.microphone")}</label>
                  <select
                    id="classbridge-microphone"
                    aria-label={t("sessionTools.recordingMicrophone")}
                    disabled={live.active || live.settling}
                    value={microphoneId}
                    onChange={(event) => chooseMicrophone(event.target.value)}
                  >
                    <option value="">{t("sessionTools.defaultMicrophone")}</option>
                    {microphoneId &&
                      !microphones.some((m) => m.deviceId === microphoneId) && (
                        <option value={microphoneId}>
                          {t("sessionTools.previousDevice")}
                        </option>
                      )}
                    {microphones
                      .filter((m) => m.deviceId !== "default")
                      .map((m, index) => (
                        <option key={m.deviceId} value={m.deviceId}>
                          {m.label || t("sessionTools.device", { number: index + 1 })}
                        </option>
                      ))}
                  </select>
                  <button
                    className="text-button"
                    type="button"
                    onClick={refreshMicrophones}
                    disabled={live.active || live.settling}
                  >
                    {t("sessionTools.refreshDevices")}
                  </button>
                  <span className="tiny muted">
                    {t("sessionDetails.current")}
                    {t(live.asrAcousticProfile === "near" ? "settings.near" : live.asrAcousticProfile === "far" ? "settings.far" : "sessionDetails.waiting")}{" "}
                    · {t("sessionDetails.next")}
                    {t(preferences.audio_processing_mode === "natural" ? "settings.natural" : "settings.standard")}
                  </span>
                  {deviceError && <span role="status">{t(deviceError)}</span>}
                  {live.appliedAudio && (
                    <span className="tiny muted">
                      {t("sessionDetails.browser")}
                      {(
                        [
                          ["echoCancellation", t("sessionDetails.echo")],
                          ["noiseSuppression", t("sessionDetails.noise")],
                          ["autoGainControl", t("sessionDetails.gain")],
                        ] as const
                      )
                        .map(
                          ([key, label]) =>
                            `${label}: ${t(live.appliedAudio?.[key] === undefined ? "settings.unreported" : live.appliedAudio[key] ? "sessionDetails.on" : "sessionDetails.off")}`,
                        )
                        .join(" · ")}
                      {t("sessionDetails.hardware")}
                    </span>
                  )}
                  {live.active && live.audioQuality && (
                    <span className="tiny muted">
                      {t("sessionDetails.peak", { peak: live.inputPeak.toFixed(2), window: Math.round(live.audioQuality.peak_window_ms) })}
                    </span>
                  )}
                  {live.active && live.audioQuality?.possible_clipping && (
                    <strong role="status">
                      {t("sessionDetails.clipping")}
                    </strong>
                  )}
                </div>
              </details>
            )}
            <div className="capture-right">
              <span>
                {session.retain_audio
                  ? session.mode === "demo"
                    ? t("sessionDetails.noDemoAudio")
                    : t("sessionDetails.retention", { count: preferences.audio_retention_days })
                  : t("sessionDetails.textOnly")}
              </span>
              <button
                className="text-button"
                disabled={live.active || live.settling || !audioAvailable}
                title={
                  audioAvailable
                    ? t("sessionDetails.reprocessHint")
                    : t("sessionDetails.noAudio")
                }
                onClick={async () => {
                  try {
                    await post(`/sessions/${session.id}/reprocess`);
                    notify(t("sessionDetails.reprocessQueued"));
                    refresh();
                  } catch (e) {
                    notify(t("common.error"));
                  }
                }}
              >
                <RefreshCw size={12} />
                {t("sessionDetails.reprocess")}
              </button>
            </div>
            {!!Object.keys(live.latency).length && (
              <div className="latency-strip">
                {session.mode === "demo"
                  ? t("sessionExtra.simulatedLatency")
                  : t("sessionExtra.latency")}
                {Object.entries(live.latency)
                  .filter(
                    ([key, value]) =>
                      [
                        "source_first_ms",
                        "source_final_ms",
                        "translation_first_ms",
                        "translation_final_ms",
                        "preview_first_ms",
                        "translation_queue_ms",
                        "translation_model_first_ms",
                        "translation_model_final_ms",
                      ].includes(key) && typeof value === "number",
                  )
                  .map(([key, value]) => (
                    <span key={key}>
                      {(
                        {
                          source_first_ms: t("sessionExtra.source_first_ms"),
                          source_final_ms: t("sessionExtra.source_final_ms"),
                          translation_first_ms: t("sessionExtra.translation_first_ms"),
                          translation_final_ms: t("sessionExtra.translation_final_ms"),
                          preview_first_ms: t("sessionExtra.preview_first_ms"),
                          translation_queue_ms: t("sessionExtra.translation_queue_ms"),
                          translation_model_first_ms: t("sessionExtra.translation_model_first_ms"),
                          translation_model_final_ms: t("sessionExtra.translation_model_final_ms"),
                        } as Record<string, string>
                      )[key] || key}{" "}
                      {Math.max(0, Math.round(Number(value)))}ms
                    </span>
                  ))}
              </div>
            )}
          </div>
        </details>
      </div>
      {live.preparing && (
        <div className="mode-banner real" role="status">
          {t("capture.preparing")}
        </div>
      )}
      {!live.preparing && live.health && (
        <details className="info-box capture-health">
          <summary role="status">{!live.active ? `${t("diagnostics.stopped")}${live.health.first_failure_code ? ` · ${live.health.first_failure_code}` : ""}` : live.browserBufferWarning ? t("diagnostics.browserDelay") : t(`diagnostics.${recognitionStatusCode(live.health)}`, { seconds: Math.floor(live.health.last_transcript_age_ms / 1000) })}</summary>
          <p className="tiny muted">
            {t("diagnostics.received")} {(live.health.received_audio_ms / 1000).toFixed(1)} s ·
            {t("diagnostics.sent")} {(live.health.sent_audio_ms / 1000).toFixed(1)} s ·
            {t("diagnostics.queued")} {live.health.queued_audio_ms} ms ·
            {t("diagnostics.level")} {live.health.input_dbfs} dBFS
          </p>
          <p className="tiny muted">
            {live.effectiveASR?.provider} / {live.effectiveASR?.model} ·
            {t("diagnostics.capture")} {live.health.capture_state || "CAPTURING"} · {t("diagnostics.recognition")} {live.health.asr_state || "STREAMING"} ·
            {t("diagnostics.browserBuffer")} {Math.round(live.browserBufferMs)} ms ·
            {t("diagnostics.batch")} {(live.health.batch_pending_pcm_bytes || 0)/32} ms ·
            {t("diagnostics.inflight")} {(live.health.upstream_inflight_pcm_bytes || 0)/32} ms ·
            {t("diagnostics.sendWait")} {live.health.current_send_wait_ms || 0} ms ·
            {t("diagnostics.archive")} {((live.health.archive_written_pcm_bytes || 0)/32000).toFixed(1)} s ({t("diagnostics.archiveHint")}) ·
            {t("diagnostics.resultQueue")} {live.health.asr_result_queue_size || 0} ·
            {t("diagnostics.eventLoop")} {live.health.event_loop_lag_ms || 0} ms ·
            {t("diagnostics.tasks")} {live.health.pending_processing_tasks || 0} ·
            {t("diagnostics.recoveryDisabled")}
          </p>
          <p className="tiny muted">{t("diagnostics.levelHint")}</p>
        </details>
      )}
      {live.notice && (
        <div className="session-notice" role="alert">
          <span>{live.notice}</span>
          <button
            className="icon-button"
            aria-label={t("common.dismiss")}
            onClick={() => live.setNotice("")}
          >
            <X size={15} />
          </button>
        </div>
      )}
      <div className="mobile-tabs">
        {[
          ["subtitles", t("transcript.title"), FileText],
          ["summary", t("stage.highlights"), Sparkles],
          ["chat", t("chat.tab"), MessageSquare],
        ].map(([key, label, Icon]) => {
          const I = Icon as typeof FileText;
          return (
            <button
              key={String(key)}
              className={tab === key ? "active" : ""}
              onClick={() => setTab(key as typeof tab)}
            >
              <I size={16} />
              {String(label)}
            </button>
          );
        })}
      </div>
      <div
        className={`session-body ${!sidebar ? "side-collapsed" : ""} mobile-${tab}`}
      >
        <section className="subtitle-panel">
          <div className="subtitle-toolbar">
            <h2>
              <AudioMark />
              {t("transcript.title")}<span>{t("transcript.count", { count: live.segments.length })}</span>
            </h2>
            <button
              className="text-button"
              aria-label={showOriginal ? t("transcript.hide") : t("transcript.show")}
              onClick={() => setShowOriginal(!showOriginal)}
            >
              {showOriginal ? <Eye size={15} /> : <EyeOff size={15} />}
              <span>{showOriginal ? t("transcript.show") : t("transcript.hide")}</span>
            </button>
          </div>
          <div
            className="subtitle-list"
            role="region"
            aria-label={t("transcript.region")}
            tabIndex={0}
            ref={list}
            onScroll={() => {
              const el = list.current;
              if (el) {
                followingRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
                setFollowing(followingRef.current);
              }
            }}
          >
            {!live.segments.length && (
              <div className="subtitle-empty">
                <span className="empty-mic">
                  <Mic size={35} />
                </span>
                <span className="eyebrow">{t("sessionExtra.ready")}</span>
                <h2>{t("transcript.empty")}</h2>
                <p>
                  {session.mode === "demo"
                    ? t("transcript.demoHint")
                    : t("transcript.realHint")}
                </p>
                <div>
                  <span>
                    <Languages size={16} />
                    {t("transcript.keep")}
                  </span>
                  <span>
                    <BookOpen size={16} />
                    {t("transcript.cite")}
                  </span>
                </div>
              </div>
            )}
            {timeline.map((item) => {
              if (item.kind === "gap") return (
                <div className="gap-marker" key={item.key}>
                  {formatTime(item.time)} · {t(`diagnostics.incident.${incidentCode(item.related)}`)}
                  {incidentCode(item.related) === "unknown" && <> · {Array.from(new Set(item.related.map(e=>e.message).filter(Boolean))).join("；") || t("diagnostics.incident.pending")}</>}
                </div>
              );
              const s = item.segment;
              return (
              <article
                className={`subtitle-segment ${!s.source_final ? "is-partial" : ""}`}
                id={`sentence-${s.sentence_id}`}
                key={item.key}
              >
                <div className="segment-meta">
                  <span className="segment-time">
                    {formatTime(s.start_ms)}
                    <span>—</span>
                    {formatTime(s.end_ms)}
                  </span>
                  <span className="segment-status">
                    {s.source_status === "interrupted" ? t("transcript.uncertain") : s.source_final ? (
                      <><Check size={12} />{t("transcript.final")}</>
                    ) : t("transcript.partial")}
                  </span>
                  {s.mode === "demo" && <span className="demo-mark">{t("transcript.demo")}</span>}
                  <span className="revision">v{s.source_revision}</span>
                  {s.speaker != null && (
                    <button
                      className="text-button"
                      disabled={live.active || live.settling}
                      title={t("sessionExtra.speakerHint")}
                      onClick={async () => {
                        const name = prompt(
                          t("sessionExtra.speakerPrompt", { speaker: s.speaker! }),
                          session.speaker_names?.[s.speaker!] || "",
                        );
                        if (name !== null) {
                          try {
                            await request(`/sessions/${session.id}/speakers`, {
                              method: "PATCH",
                              body: JSON.stringify({
                                mapping: {
                                  ...session.speaker_names,
                                  [s.speaker!]: name,
                                },
                              }),
                            });
                            refresh();
                          } catch (e) {
                            notify(t("common.error"));
                          }
                        }
                      }}
                    >
                      {session.speaker_names?.[s.speaker] ||
                        t("sessionExtra.speaker", { speaker: s.speaker })}
                    </button>
                  )}
                </div>
                {(showOriginal || s.source_status === "interrupted") && (
                  <p className="source-text" lang="und">
                    {!s.source_final && s.stable_preview !== undefined ? <>
                      <span className="stable-source-preview" title={t("transcript.stable")}>{s.stable_preview}</span>
                      <span className="unstable-source-tail" title={t("transcript.unstable")}>{s.unstable_tail}</span>
                    </> : s.text || t("transcript.wait")}
                  </p>
                )}
                <p
                  lang={target}
                  dir={translationDirection(target)}
                  className={`translation-text ${!s.translation_final ? "temporary" : ""}`}
                  style={{ fontSize: preferences.subtitle_size || 24 }}
                >
                  {s.source_status === "interrupted" ? t("translation.unconfirmed") : s.translation || (s.translation_status === "failed" ? t("translation.failed") : (
                    <span className="translation-waiting">
                      <span className="typing-dots">•••</span> {t("translation.wait", { language: targetLabel })}
                    </span>
                  ))}
                </p>
                {s.translation && s.translation_status === "failed" && <small className="temporary-label" role="status">{t("translation.updateFailed")}</small>}
                {s.translation_final && <small className="translation-status">{t("translation.done", { language: targetLabel })}</small>}
                {s.translation && !s.translation_final && s.translation_status !== "failed" && (
                  <small className="temporary-label">
                    {s.source_final ? t("translation.temporary", { language: targetLabel }) : s.preview_source_text ? t("translation.preview") : t("translation.revisable")}
                  </small>
                )}
                {s.provenance === "user_correction" && <button className="text-button" onClick={() => void jumpEvidence(s.sentence_id, s.source_revision - 1)}>
                  {t("sessionExtra.corrected", { revision: s.source_revision - 1 })}
                </button>}
              </article>
              );
            })}
            <div ref={end} className="subtitle-bottom" />
          </div>
          {!following && !!live.segments.length && (
            <button
              className="follow-button"
              onClick={() => {
                setFollowing(true);
                end.current?.scrollIntoView({ behavior: "smooth" });
              }}
            >
              <ArrowDown size={14} />
              {t("transcript.latest")}
            </button>
          )}
        </section>
        <aside className="insight-sidebar">
          <div className="insight-tabs">
            <button
              className={sideTab === "summary" ? "active" : ""}
              onClick={() => setSideTab("summary")}
            >
              <Sparkles size={16} />
              {t("stage.highlights")}
            </button>
            <button
              className={sideTab === "chat" ? "active" : ""}
              onClick={() => setSideTab("chat")}
            >
              <MessageSquare size={16} />
              {t("chat.tab")}
            </button>
          </div>
          <div
            className={`summary-container ${sideTab === "summary" ? "side-active" : ""}`}
          >
            <StagePanel
              stages={session.stages || []}
              busy={busy}
              generate={() => void summarize()}
              jump={(id, revision) => void jumpEvidence(id, revision)}
            />
          </div>
          <div
            className={`chat-container ${sideTab === "chat" ? "side-active" : ""}`}
          >
            <Chat
              sessionId={session.id}
              mode={session.mode}
              onCitation={citation}
            />
          </div>
        </aside>
      </div>
      <div className="capture-bar" aria-label={t("capture.controls")}>
        <div className="capture-left">
          <span
            className={`connection-dot ${live.connection === "connected" ? "connected" : ""}`}
          />
          <div>
            <strong>{t(`capture.${live.connection}`)}</strong>
            <small>
              <Wifi size={11} />
              {t("capture.queue", { count: live.queue })}
            </small>
          </div>
          <div className="capture-divider" />
          <span className="capture-time" title={t("capture.time")}>
            {formatTime(live.elapsed)}
            <small>/ 105:00</small>
          </span>
          {session.mode === "real" && (
            <div
              className="volume-meter"
              title={t("capture.volume", { value: Math.round(live.level * 100) })}
            >
              <Volume2 size={16} />
              <div>
                <i style={{ width: `${Math.min(100, live.level * 400)}%` }} />
              </div>
            </div>
          )}
        </div>
        <div className="capture-main">
          {live.active ? (
            <button className="stop-button" onClick={() => live.stop()}>
              <Square size={16} fill="currentColor" />
              {live.preparing ? t("capture.cancel") : t(session.mode === "demo" ? "capture.stopDemo" : "capture.stop")}
            </button>
          ) : (
            <button
              className="primary capture-start"
              disabled={
                modelBusy || live.settling ||
                live.connection !== "connected" ||
                live.elapsed >= 105 * 60 * 1000
              }
              onClick={() => void live.start()}
            >
              {session.mode === "demo" ? (
                <Sparkles size={18} />
              ) : (
                <Mic size={18} />
              )}
              <span>{t(session.mode === "demo" ? "capture.startDemo" : "capture.start")}</span>
            </button>
          )}
          {live.connection !== "connected" && !live.active && (
            <button className="secondary" onClick={live.retry}>
              {t("capture.retry")}
            </button>
          )}
        </div>
      </div>
      {!!session.tasks?.some(
        (t) =>
          t.kind === "export" || t.status === "failed" || t.status === "retry",
      ) && (
        <details className="task-status">
          <summary>
            {t("sessionExtra.tasks", { count: session.tasks.filter(
              (task) => task.status === "failed" || task.status === "retry",
            ).length })}
          </summary>
          {session.tasks
            .filter(
              (t) =>
                t.kind === "export" ||
                t.status === "failed" ||
                t.status === "retry",
            )
            .map((task) => (
              <p key={task.id}>
                {(
                  {
                    translate: t("sessionExtra.translate"),
                    index_segment: t("sessionExtra.index_segment"),
                    summarize: t("sessionExtra.summarize"),
                    reprocess: t("sessionExtra.reprocess"),
                    export: t("sessionExtra.export"),
                  } as Record<string, string>
                )[task.kind] || task.kind}{" "}
                ·{" "}
                {(
                  {
                    retry: t("sessionExtra.retry"),
                    failed: t("sessionExtra.failed"),
                    completed: t("sessionExtra.completed"),
                    pending: t("sessionExtra.pendingTask"),
                    running: t("sessionExtra.running"),
                  } as Record<string, string>
                )[task.status] || task.status}
                {task.error && `: ${t("common.error")}`}
                {task.kind === "export" && task.status === "completed" && (
                  <a
                    className="text-button"
                    href={`/api/sessions/${session.id}/exports/${task.id}/file`}
                    download
                  >
                    {t("sessionExtra.download")}
                  </a>
                )}
              </p>
            ))}
        </details>
      )}
      {selectedSource?.kind === "document" && selectedSource.document_id && (
        <DocumentPreview
          documentId={selectedSource.document_id}
          chunkId={selectedSource.chunk_id}
          page={selectedSource.page}
          quote={selectedSource.quote}
          close={() => setSelectedSource(null)}
        />
      )}
      {documentsOpen && (
        <Dialog title={t("sessionTools.documents")} className="session-documents" close={() => setDocumentsOpen(false)}>
            <div className="modal-title">
              <h2>{t("sessionTools.documents")}</h2>
              <button
                className="icon-button"
                aria-label={t("sessionExtra.closeDocuments")}
                onClick={() => setDocumentsOpen(false)}
              >
                <X size={20} />
              </button>
            </div>
            <Library
              sessionId={session.id}
              defaultMode={session.mode}
              notify={notify}
            />
        </Dialog>
      )}
      {selectedSource?.kind === "sentence" && (
        <div className="source-popover" role="dialog" aria-label={t("sessionExtra.quote")}>
          <div>
            <strong>
              {t("sessionExtra.evidence", { revision: selectedSource.source_revision || 1 })}
            </strong>
            <button
              className="icon-button"
              aria-label={t("sessionExtra.closeQuote")}
              onClick={() => setSelectedSource(null)}
            >
              <X size={16} />
            </button>
          </div>
          <blockquote>{selectedSource.quote}</blockquote>
          {selectedSource.session_id &&
            selectedSource.session_id !== session.id && (
              <button
                className="text-button"
                disabled={live.active || live.settling}
                onClick={() => {
                  openSession(selectedSource.session_id!);
                  setSelectedSource(null);
                }}
              >
                {t("sessionExtra.openSource")}
              </button>
            )}
        </div>
      )}
    </div>
  );
}
function AudioMark() {
  return (
    <span className="audio-mark">
      <i />
      <i />
      <i />
      <i />
    </span>
  );
}
