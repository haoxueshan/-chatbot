import { translationLanguages, translationLanguageLabel, formatTranslationTerms, parseTranslationTerms, type TargetLanguage } from "../lib/translationLanguages";
import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Check,
  Languages,
  Monitor,
  Moon,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
} from "lucide-react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Textarea } from "./ui/input";
import type { Preferences } from "../lib/types";
import { classroomPreset } from "../lib/classroomPreset";
import { asrLanguageLabels, type ASRLanguageMode } from "../lib/asrLanguages";
import { ASRModels } from "./ASRModels";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { useI18n } from "../i18n/I18nProvider";
export function Settings({
  preferences,
  save,
}: {
  preferences: Preferences;
  save: (p: Preferences) => Promise<void>;
}) {
  const { t, language } = useI18n();
  const [savedTarget, setSavedTarget] = useState(preferences.target_language);
  const [draft, setDraft] = useState(preferences),
    [terms, setTerms] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const previousPreferences = useRef<Preferences | null>(null);
  useEffect(() => {
    const { ui_language: _language, ...current } = preferences;
    const { ui_language: _previousLanguage, ...previous } = previousPreferences.current || {};
    previousPreferences.current = preferences;
    // A locale-only server refresh must not discard unsaved settings or terms.
    if (JSON.stringify(current) === JSON.stringify(previous)) return;
    setDraft(preferences);
    setTerms(formatTranslationTerms(preferences.terms));
  }, [preferences]);
  const submit = async () => {
    setBusy(true);
    setMessage("");
    try {
      const parsed = terms === formatTranslationTerms(preferences.terms) ? preferences.terms : parseTranslationTerms(terms);
      await save({ ...draft, terms: parsed });
      setSavedTarget(draft.target_language);
      setMessage("saved");
    } catch (e) {
      setMessage("failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="settings page-scroll">
      <div className="settings-width">
        <div className="page-heading">
          <div>
            <span className="eyebrow">{t("settings.eyebrow")}</span>
            <h1>{t("navigation.settings")}</h1>
            <p>{t("settings.intro")}</p>
          </div>
          <Button disabled={busy} onClick={() => void submit()}>
            <Save size={16} />
            {busy ? t("settings.saving") : t("settings.save")}
          </Button>
        </div>
        <nav className="settings-navigation" aria-label={t("settings.groups")}>
          {[["appearance", t("settings.appearance")], ["language", t("settings.termsNav")], ["microphone", t("settings.microphone")],
            ["privacy", t("settings.privacy")], ["services", t("settings.servicesNav")], ["asr", t("settings.asrNav")]].map(([id, label]) => (
            <button key={id} onClick={() => {
              const section = document.getElementById(`settings-${id}`);
              section?.focus({preventScroll: true});
              section?.scrollIntoView({block: "start"});
            }}>{label}</button>
          ))}
        </nav>
        {message && (
          <div role="status" className="info-box">
            {t(message === "saved" ? "settings.savedNotice" : "settings.failedNotice", {
              language: language === "zh-CN"
                ? translationLanguageLabel(savedTarget)
                : new Intl.DisplayNames([language], { type: "language" }).of(savedTarget || "zh-CN") || savedTarget || "zh-CN",
            })}
          </div>
        )}
        <Card id="settings-appearance" tabIndex={-1} className="settings-card">
          <div className="settings-row">
            <div>
              <strong>{t("settings.language")}</strong>
              <small>{t("settings.languageDescription")}</small>
            </div>
            <LanguageSwitcher />
          </div>
          <div className="settings-title">
            <span className="quick-icon purple">
              <SlidersHorizontal size={21} />
            </span>
            <div>
              <h2>{t("settings.appearance")}</h2>
              <p>{t("settings.appearanceHint")}</p>
            </div>
          </div>
          <div className="settings-row">
            <div>
              <strong>{t("settings.theme")}</strong>
              <small>{t("settings.themeHint")}</small>
            </div>
            <div className="segmented theme-choice">
              <button
                className={draft.theme === "light" ? "active" : ""}
                onClick={() => setDraft({ ...draft, theme: "light" })}
              >
                <Sun size={15} />
                {t("settings.light")}
              </button>
              <button
                className={draft.theme === "dark" ? "active" : ""}
                onClick={() => setDraft({ ...draft, theme: "dark" })}
              >
                <Moon size={15} />
                {t("settings.dark")}
              </button>
            </div>
          </div>
          <div className="settings-row">
            <div>
              <strong>{t("settings.size")}</strong>
              <small>{t("settings.sizeHint")}</small>
            </div>
            <div className="range-control">
              <input
                aria-label={t("settings.size")}
                type="range"
                min={18}
                max={44}
                step={2}
                value={draft.subtitle_size}
                onChange={(e) =>
                  setDraft({ ...draft, subtitle_size: Number(e.target.value) })
                }
              />
              <span>{draft.subtitle_size}px</span>
            </div>
          </div>
          <div className="subtitle-preview">
            <small>Learning begins with a question.</small>
            <p style={{ fontSize: draft.subtitle_size }}>
              {t("settings.preview")}
            </p>
          </div>
          <label className="settings-row">
            <div>
              <strong>{t("settings.original")}</strong>
              <small>{t("settings.originalHint")}</small>
            </div>
            <input
              className="switch"
              type="checkbox"
              checked={draft.show_original}
              onChange={(e) =>
                setDraft({ ...draft, show_original: e.target.checked })
              }
            />
          </label>
        </Card>
        <Card id="settings-language" tabIndex={-1} className="settings-card">
          <div className="settings-title">
            <span className="quick-icon blue">
              <Languages size={21} />
            </span>
            <div>
              <h2>{t("settings.terms")}</h2>
              <p>{t("settings.termsHint")}</p>
            </div>
          </div>
          <button
            type="button"
            className="secondary"
            onClick={() => setDraft(classroomPreset(draft))}
          >
            {t("settings.preset")}
          </button>
          <label className="settings-row">
            <div>
              <strong>{t("settings.asrLanguage")}</strong>
              <small>
                {t("settings.asrHint")}
              </small>
            </div>
            <select
              aria-label={t("settings.asrLanguage")}
              value={draft.asr_language_mode || "auto"}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  asr_language_mode: e.target.value as ASRLanguageMode,
                })
              }
            >
              {Object.keys(asrLanguageLabels).map((value) => (
                <option key={value} value={value}>
                  {t(value === "auto" ? "settings.asrAuto" : value === "ko_en" ? "settings.asrKoEn" : "settings.asrKo")}
                </option>
              ))}
            </select>
          </label>
          <label className="settings-row">
            <div><strong>{t("settings.target")}</strong><small>{t("settings.targetHint")}</small></div>
            <select aria-label={t("settings.target")} value={draft.target_language || "zh-CN"} onChange={e=>setDraft({...draft,target_language:e.target.value as TargetLanguage})}>
              {Object.entries(translationLanguages).map(([code, item])=><option key={code} value={code}>{language === "zh-CN" ? item.label : new Intl.DisplayNames([language], { type: "language" }).of(code) || item.label}</option>)}
            </select>
          </label>
          <label className="terms-label">
            {t("settings.termTitle")}
            <small>
              {t("settings.termHelp")}
            </small>
            <Textarea
              rows={6}
              maxLength={12000}
              value={terms}
              onChange={(e) => setTerms(e.target.value)}
              placeholder={"작업기억 = 工作记忆\n인지부하 = 认知负荷"}
            />
          </label>
          {preferences.asr_terms_status && (
            <div className="info-box" role="status">
              <div>
                <strong>
                  {t("settings.termCount", { count: preferences.asr_terms_status.enabled_count })}
                </strong>
                {!preferences.asr_terms_status.enabled_count && (
                  <p>
                    {t("settings.termEmpty")}
                  </p>
                )}
                {preferences.asr_terms_status.skipped.map((item) => (
                  <p key={item.index}>
                    {t("settings.termSkipped", { index: item.index + 1 })}: {item.reason}
                  </p>
                ))}
              </div>
            </div>
          )}
          <label className="settings-row">
            <div>
              <strong>{t("settings.hotword")}</strong>
              <small>
                {t("settings.weightHelp")}
              </small>
            </div>
            <select
              aria-label={t("settings.hotword")}
              value={draft.asr_hotword_weight ?? 2}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  asr_hotword_weight: Number(e.target.value) as 2 | 3 | 4,
                })
              }
            >
              <option value={2}>{t("settings.weightLight")}</option>
              <option value={3}>{t("settings.weightNormal")}</option>
              <option value={4}>{t("settings.weightStrong")}</option>
            </select>
          </label>
          <label className="terms-label">
            {t("settings.contextTitle")}
            <small>
              {t("settings.contextHelp")}
            </small>
            <Textarea
              aria-label={t("settings.context")}
              rows={4}
              maxLength={400}
              value={draft.asr_context || ""}
              onChange={(e) =>
                setDraft({ ...draft, asr_context: e.target.value })
              }
              placeholder={t("settings.contextPlaceholder")}
            />
            <small>
              {Array.from(draft.asr_context || "").length} / 400 ·
              {t("settings.exampleHint")}
            </small>
          </label>
        </Card>
        <Card id="settings-microphone" tabIndex={-1} className="settings-card">
          <div className="settings-title">
            <span className="quick-icon orange">
              <ShieldCheck size={21} />
            </span>
            <div>
              <h2>{t("settings.recording")}</h2>
              <p>{t("settings.recordingHint")}</p>
            </div>
          </div>
          <label className="settings-row">
            <div>
              <strong>{t("settings.acoustic")}</strong>
              <small>
                {t("settings.acousticHelp")}
              </small>
            </div>
            <select
              aria-label={t("settings.acoustic")}
              value={draft.asr_acoustic_profile || "far"}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  asr_acoustic_profile: e.target.value as "far" | "near",
                })
              }
            >
              <option value="far">{t("settings.far")}</option>
              <option value="near">{t("settings.near")}</option>
            </select>
          </label>
          <label className="settings-row">
            <div>
              <strong>{t("settings.processing")}</strong>
              <small>
                {t("settings.processingHelp")}
              </small>
            </div>
            <select
              aria-label={t("settings.processing")}
              value={draft.audio_processing_mode || "standard"}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  audio_processing_mode: e.target.value as
                    "standard" | "natural",
                })
              }
            >
              <option value="standard">{t("settings.standard")}</option>
              <option value="natural">{t("settings.natural")}</option>
            </select>
          </label>
        </Card>
        <Card id="settings-privacy" tabIndex={-1} className="settings-card">
          <div className="settings-title">
            <span className="quick-icon">
              <ShieldCheck size={21} />
            </span>
            <div>
              <h2>{t("settings.privacy")}</h2>
              <p>{t("settings.privacyHint")}</p>
            </div>
          </div>
          <label className="settings-row">
            <div>
              <strong>{t("settings.retain")}</strong>
              <small>{t("settings.retainHint")}</small>
            </div>
            <input
              className="switch"
              type="checkbox"
              checked={draft.retain_audio}
              onChange={(e) =>
                setDraft({ ...draft, retain_audio: e.target.checked })
              }
            />
          </label>
          <div className="settings-row">
            <div>
              <strong>{t("settings.retention")}</strong>
              <small>{t("settings.retentionHint")}</small>
            </div>
            <span>{t("settings.days", { count: draft.audio_retention_days })}</span>
          </div>
          <div className="info-box">
            <BookOpen size={17} />
            <span>
              {t("settings.storageHelp")}
            </span>
          </div>
        </Card>
        <Card id="settings-services" tabIndex={-1} className="settings-card">
          <div className="settings-title">
            <span className="quick-icon purple">
              <Monitor size={21} />
            </span>
            <div>
              <h2>{t("settings.services")}</h2>
              <p>{t("settings.servicesHint")}</p>
            </div>
          </div>
          <div className="model-status">
            <span className={`badge ${draft.api_key_configured && !draft.aliyun_services_error ? "green" : "amber"}`}>
              {draft.api_key_configured && !draft.aliyun_services_error ? (
                <>
                  <Check size={13} />
                  {t("settings.configured")}
                </>
              ) : (
                t("settings.notReady")
              )}
            </span>
            <span className="tiny muted">
              {t("settings.region", { region: draft.region || t("settings.unreported") })}
            </span>
          </div>
          <div className="model-table">
            {Object.entries(draft.models || {}).filter(([name])=>name!=="asr").map(([name, value]) => (
              <div key={name}>
                <span>
                  {{
                    asr: t("settings.modelASR"),
                    translation: t("settings.modelTranslation"),
                    summary: t("settings.modelSummary"),
                    answer: t("settings.modelAnswer"),
                    embedding: t("settings.modelEmbedding"),
                    rerank: t("settings.modelRerank"),
                  }[name] || name}
                </span>
                <code>{value}</code>
              </div>
            ))}
          </div>
          <div className="config-checks">
            <span>{draft.api_key_configured ? "✓" : "○"} {t("settings.serverKey")}</span>
            <span>
              {draft.workspace_configured
                ? `✓ ${t("settings.workspace")}`
                : draft.api_key_configured && !draft.aliyun_services_error
                  ? `✓ ${t("settings.endpointConfigured")}`
                  : `○ ${t("settings.workspaceOrEndpoint")}`}
            </span>
          </div>
          {draft.aliyun_services_error && (
            <p role="status" className="info-box">
              {t("settings.notReady")}
            </p>
          )}
          <p className="tiny muted">
            DASHSCOPE_API_KEY
            {t("settings.keyHelp")}
          </p>
        </Card>
        <div className="info-box">
          {t("settings.limitHelp")}
        </div>
        <ASRModels />
        <footer className="page-footer">
          <span>ClassBridge · v1.0</span>
          <span>{t("settings.credit")}</span>
        </footer>
      </div>
    </div>
  );
}
