import test from "node:test";
import assert from "node:assert/strict";
import { locales, zhCN, translate, isUILanguage, readLanguage, storeLanguage, formatDate, formatNumber, formatRelative, type TranslationKey } from "../src/i18n/index";

test("locale keys and interpolation placeholders match the Chinese baseline", () => {
  const keys = Object.keys(zhCN).sort();
  for (const locale of Object.values(locales)) {
    assert.deepEqual(Object.keys(locale).sort(), keys);
    for (const key of keys as TranslationKey[]) {
      assert.ok(locale[key].trim());
      const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort();
      assert.deepEqual(placeholders(locale[key]), placeholders(zhCN[key]));
    }
  }
});
test("interpolation and English singular/plural", () => {
  assert.equal(translate("en", "sessions.count", { count: 1 }), "1 session");
  assert.equal(translate("en", "sessions.count", { count: 2 }), "2 sessions");
  assert.equal(translate("ko", "sessions.count", { count: 3 }), "세션 3개");
});
test("unknown keys do not expose internal identifiers", () => {
  assert.equal(translate("en", "missing.internal" as TranslationKey), locales.en["common.error"]);
  assert.equal(translate("en", "__proto__" as TranslationKey), locales.en["common.error"]);
});
test("supported languages are explicit and storage is optional", () => {
  assert.ok(isUILanguage("zh-CN"));
  assert.ok(isUILanguage("en"));
  assert.ok(isUILanguage("ko"));
  assert.equal(isUILanguage("fr"), false);
  assert.equal(isUILanguage(null), false);
  assert.equal(readLanguage(), "zh-CN");
  assert.doesNotThrow(() => storeLanguage("ko"));
});
test("Intl helpers use the requested locale without changing timezone", () => {
  const value = new Date(2026, 10, 26, 12);
  for (const language of ["zh-CN", "en", "ko"] as const) {
    assert.equal(formatDate(language, value), new Intl.DateTimeFormat(language, { dateStyle: "long" }).format(value));
    assert.equal(formatNumber(language, 12345), new Intl.NumberFormat(language).format(12345));
    assert.equal(formatRelative(language, -1, "day"), new Intl.RelativeTimeFormat(language, { numeric: "auto" }).format(-1, "day"));
  }
});