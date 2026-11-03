import registry from "../../../backend/app/data/translation_languages.json";
export const translationLanguages = registry;
export type TargetLanguage = keyof typeof translationLanguages;
const supported = (code: string): code is TargetLanguage =>
  Object.prototype.hasOwnProperty.call(translationLanguages, code);
export function translationLanguageLabel(code: string = "zh-CN"): string {
  return supported(code) ? translationLanguages[code].label : "未知语言";
}
export function translationDirection(code: TargetLanguage = "zh-CN"): "rtl" | "ltr" {
  return translationLanguages[code].dir === "rtl" ? "rtl" : "ltr";
}

export function formatTranslationTerms(terms: (string | Record<string,string>)[]): string {
  return terms.map(t=>typeof t === "string" ? t : `${t.target_language ? `[${t.target_language}] ` : ""}${t.source || t.term || ""} = ${t.target || t.translation || ""}`).join("\n");
}
export function parseTranslationTerms(text: string): (string | Record<string,string>)[] {
  return text.split("\n").map(s=>s.trim()).filter(Boolean).map(line=>{
    const tag=line.match(/^\[([^\]]+)\]\s*(.*)$/);
    if (tag && !supported(tag[1])) throw new Error("术语包含不支持的目标语言代码");
    const [source,...target]=(tag ? tag[2] : line).split("=");
    if (!target.length) return line;
    return {source:source.trim(),target:target.join("=").trim(),...(tag ? {target_language:tag[1]} : {})};
  });
}
