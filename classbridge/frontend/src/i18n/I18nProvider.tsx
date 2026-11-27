import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { isUILanguage, readLanguage, storeLanguage, translate, type UILanguage, type TranslationKey } from "./index";
import { request } from "../lib/api";

type Translator = (key: TranslationKey, params?: Record<string, string | number>) => string;
interface I18nContextValue {
  language: UILanguage;
  setLanguage: (language: UILanguage) => void;
  t: Translator;
  saving: boolean;
  failed: boolean;
}
const Context = createContext<I18nContextValue>({
  language: "zh-CN", setLanguage: () => {}, t: (key, params) => translate("zh-CN", key, params),
  saving: false, failed: false,
});
export function I18nProvider({ children, persist, userId }: {
  children: ReactNode;
  persist?: (language: UILanguage) => Promise<void>;
  userId?: string;
}) {
  const [language, update] = useState<UILanguage>(readLanguage);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const queue = useRef(Promise.resolve());
  const revision = useRef(0);
  const persistRef = useRef(persist);
  const account = useRef(userId);
  account.current = userId;
  persistRef.current = persist || (userId ? async (next) => {
    if (account.current !== userId) return;
    await request("/settings", { method: "PATCH", body: JSON.stringify({ ui_language: next }) });
  } : undefined);
  useEffect(() => {
    const version = ++revision.current;
    setSaving(false);
    setFailed(false);
    if (!userId) return;
    let cancelled = false;
    void request<{ ui_language?: unknown }>("/settings").then(value => {
      if (cancelled || version !== revision.current) return;
      const next = isUILanguage(value.ui_language) ? value.ui_language : readLanguage();
      update(next);
      storeLanguage(next);
    }).catch(() => {
      if (!cancelled && version === revision.current) setFailed(true);
    });
    return () => { cancelled = true; };
  }, [userId]);
  const setLanguage = useCallback((next: UILanguage) => {
    if (!isUILanguage(next)) return;
    update(next);
    storeLanguage(next);
    const version = ++revision.current;
    const save = persistRef.current;
    setFailed(false);
    if (!save) { setSaving(false); return; }
    setSaving(true);
    // Serialize writes: a slow older request cannot persist after the latest one.
    queue.current = queue.current.catch(() => {}).then(async () => {
      try {
        await save(next);
        if (version === revision.current) setFailed(false);
      } catch {
        if (version === revision.current) setFailed(true);
      } finally {
        if (version === revision.current) setSaving(false);
      }
    });
  }, []);
  useEffect(() => {
    document.documentElement.lang = language;
    document.title = translate(language, "common.title");
  }, [language]);
  const t: Translator = useCallback((key, params) => translate(language, key, params), [language]);
  const value = useMemo(() => ({ language, setLanguage, t, saving, failed }), [language, setLanguage, t, saving, failed]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useI18n() { return useContext(Context); }