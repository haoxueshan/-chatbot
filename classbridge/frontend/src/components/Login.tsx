import { useState, type FormEvent } from "react";
import {
  ArrowRight,
  AudioLines,
  BookOpen,
  Languages,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { post } from "../lib/api";
import type { User } from "../lib/types";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { useI18n } from "../i18n/I18nProvider";
export function Login({ done }: { done: (u: User) => void }) {
  const { t } = useI18n();
  const [username, setUsername] = useState("admin"),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      done(await post<User>("/auth/login", { username, password }));
    } catch (err) {
      setError("failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="login">
      <div style={{ position: "absolute", right: 16, top: 16, zIndex: 2 }}><LanguageSwitcher /></div>
      <section className="login-story">
        <div className="brand light">
          <span className="brand-icon">
            <AudioLines />
          </span>
          <span>
            ClassBridge<small>{t("auth.brand")}</small>
          </span>
        </div>
        <div className="login-main">
          <span className="eyebrow light">
            <span />
            {t("auth.eyebrow")}
          </span>
          <h1>
            {t("auth.focus")}
            <br />
            {t("auth.understand")}
          </h1>
          <p>
            {t("auth.intro")}
            <br />
            {t("auth.explore")}
          </p>
          <div className="sample-caption">
            <div>
              <span className="tag">{t("auth.sample")}</span>
              <Languages size={18} />
            </div>
            <p>Learning begins with asking good questions.</p>
            <strong>学习，始于提出好问题。</strong>
            <span className="sample-line" />
          </div>
          <div className="feature-row">
            <span>
              <AudioLines size={17} />
              {t("auth.captions")}
            </span>
            <span>
              <BookOpen size={17} />
              {t("auth.knowledge")}
            </span>
            <span>
              <Sparkles size={17} />
              {t("auth.evidence")}
            </span>
          </div>
        </div>
        <span className="login-foot">{t("auth.footer")}</span>
      </section>
      <section className="login-form">
        <div className="login-box">
          <div className="lock-mark">
            <LockKeyhole size={25} />
          </div>
          <span className="eyebrow">{t("auth.private")}</span>
          <h2>{t("auth.welcome")}</h2>
          <p className="muted">{t("auth.continue")}</p>
          <form onSubmit={submit}>
            <label>
              {t("auth.username")}
              <input
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label>
              {t("auth.password")}
              <input
                autoComplete="current-password"
                required
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && (
              <div role="alert" className="error-box">
                {t("auth.failed")}
              </div>
            )}
            <button className="primary full" disabled={busy}>
              {busy ? t("auth.busy") : t("auth.submit")}
              <ArrowRight size={17} />
            </button>
          </form>
          <div className="login-note">
            <ShieldCheck size={17} />
            <p>
              {t("auth.registration")}
            </p>
          </div>
          <p className="tiny muted">
            {t("auth.demo")}
          </p>
        </div>
      </section>
    </main>
  );
}
