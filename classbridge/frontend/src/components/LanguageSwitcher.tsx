import { Globe } from "lucide-react";
import { isUILanguage, uiLanguages } from "../i18n";
import { useI18n } from "../i18n/I18nProvider";

export function LanguageSwitcher() {
  const { language, setLanguage, t, saving, failed } = useI18n();
  return (
    <div className="language-switcher">
      <label style={{ display: "inline-flex", alignItems: "center", gap: 6, maxWidth: "100%" }}>
        <Globe size={16} aria-hidden="true" />
        <select
          aria-label={t("settings.language")}
          title={t("settings.language")}
          value={language}
          onChange={event => {
            if (isUILanguage(event.target.value)) setLanguage(event.target.value);
          }}
        >
          {Object.entries(uiLanguages).map(([value, option]) =>
            <option key={value} value={value}>{option.label}</option>
          )}
        </select>
      </label>
      {saving && <span role="status" className="tiny muted">{t("settings.languageSaving")}</span>}
      {failed && <p role="alert" className="error-box">{t("settings.languageFailed")}</p>}
    </div>
  );
}