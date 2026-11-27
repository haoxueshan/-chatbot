import { sessionExtraZh, sessionExtraEn, sessionExtraKo } from "./sessionExtra";
import { sessionDetailsZh, sessionDetailsEn, sessionDetailsKo } from "./sessionDetails";
import { settingsHelpZh, settingsHelpEn, settingsHelpKo } from "./settingsHelp";
import { sessionToolsZh, sessionToolsEn, sessionToolsKo } from "./sessionTools";
import { asrModelsZh, asrModelsEn, asrModelsKo } from "./asrModels";
import { diagnosticsZh, diagnosticsEn, diagnosticsKo } from "./diagnostics";
import { captureZh, captureEn, captureKo } from "./capture";
import { stageZh, stageEn, stageKo } from "./stage";
import { settingsZh, settingsEn, settingsKo } from "./settings";
import { libraryZh, libraryEn, libraryKo } from "./library";
import { foldersZh, foldersEn, foldersKo } from "./folders";
import { homeZh, homeEn, homeKo } from "./home";
import { newSessionZh, newSessionEn, newSessionKo } from "./newSession";
import { chatZh, chatEn, chatKo } from "./chat";

export type UILanguage = "zh-CN" | "en" | "ko";
export const uiLanguages = {
  "zh-CN": { label: "简体中文", shortLabel: "中文" },
  en: { label: "English", shortLabel: "EN" },
  ko: { label: "한국어", shortLabel: "KO" },
} as const;
export function isUILanguage(value: unknown): value is UILanguage {
  return value === "zh-CN" || value === "en" || value === "ko";
}
export const storageKey = "classbridge.ui_language";
export function readLanguage(): UILanguage {
  try {
    const value = localStorage.getItem(storageKey);
    return isUILanguage(value) ? value : "zh-CN";
  } catch { return "zh-CN"; }
}
export function storeLanguage(language: UILanguage) {
  try { localStorage.setItem(storageKey, language); } catch { /* Storage is optional. */ }
}
export const zhCN = {
  ...sessionExtraZh,
  ...sessionDetailsZh,
  ...settingsHelpZh,
  ...sessionToolsZh,
  ...asrModelsZh,
  ...diagnosticsZh,
  ...captureZh,
  ...stageZh,
  ...settingsZh,
  ...libraryZh,
  ...foldersZh,
  ...homeZh,
  ...newSessionZh,
  ...chatZh,
  "auth.brand": "语音理解工作台",
  "auth.eyebrow": "让理解，跨越语言",
  "auth.focus": "专注此刻。",
  "auth.understand": "每一句，都听懂。",
  "auth.intro": "让韩语、英语课堂自然流入你的中文笔记。",
  "auth.explore": "听见原文，理解知识，带着证据继续探索。",
  "auth.sample": "产品示意 · 非实时字幕",
  "auth.captions": "双语字幕",
  "auth.knowledge": "知识沉淀",
  "auth.evidence": "循证问答",
  "auth.footer": "从声音到理解，从课堂到知识。",
  "auth.private": "你的私人学习空间",
  "auth.welcome": "欢迎回来",
  "auth.continue": "登录 ClassBridge，继续你的理解之旅。",
  "auth.username": "用户名",
  "auth.password": "密码",
  "auth.busy": "正在登录…",
  "auth.submit": "进入工作台",
  "auth.failed": "登录失败，请检查账号、密码和网络连接。",
  "auth.registration": "仅限已创建的私人账户。管理员需在服务器初始化；公开注册已关闭。",
  "auth.demo": "首次体验？登录后创建「模拟演示」会话即可，演示不调用付费 API。",
  "common.title": "ClassBridge · 语音理解工作台",
  "common.error": "操作失败，请重试。",
  "settings.language": "界面显示语言",
  "settings.languageDescription": "仅改变系统界面文字，不影响语音识别和字幕翻译语言。",
  "settings.languageSaving": "界面语言正在保存…",
  "settings.languageFailed": "当前界面语言已在本地应用，但未能保存到账户。请重新选择以重试。",
  "navigation.workspace": "工作空间导航",
  "navigation.brand": "ClassBridge 工作台",
  "navigation.close": "关闭导航",
  "navigation.open": "打开导航",
  "navigation.main": "主导航",
  "navigation.expand": "展开侧边栏",
  "navigation.collapse": "折叠侧边栏",
  "navigation.private": "私人空间",
  "navigation.privateWorkspace": "私人工作空间",
  "navigation.privacy": "音频与资料默认私有",
  "navigation.networkHint": "浏览器网络状态，不代表识别服务已连接",
  "navigation.online": "网络可用",
  "navigation.offline": "网络离线",
  "navigation.light": "切换浅色主题",
  "navigation.dark": "切换深色主题",
  "navigation.logout": "退出登录",
  "navigation.live": "实时会话",
  "sessions.new": "新建会话",
  "sessions.recent": "最近会话",
  "sessions.empty": "暂无已保存的会话",
  "sessions.demoSuffix": " · 模拟",
  "common.dismiss": "关闭提示",
  "common.opening": "正在打开你的工作台…",
  "common.loadingSession": "正在读取会话…",
  "common.offline": "网络已断开。已保存内容不会丢失，实时采集需要连接服务器。",
  "navigation.home": "工作台",
  "navigation.library": "资料库",
  "navigation.settings": "偏好设置",
  "sessions.count": "{count} 个会话",
  "sessions.count_one": "{count} 个会话",
} as const;
export type TranslationKey = keyof typeof zhCN;
type Locale = Record<TranslationKey, string>;
export const en: Locale = {
  ...sessionExtraEn,
  ...sessionDetailsEn,
  ...settingsHelpEn,
  ...sessionToolsEn,
  ...asrModelsEn,
  ...diagnosticsEn,
  ...captureEn,
  ...stageEn,
  ...settingsEn,
  ...libraryEn,
  ...foldersEn,
  ...homeEn,
  ...newSessionEn,
  ...chatEn,
  "auth.brand": "Speech Workspace",
  "auth.eyebrow": "Understanding beyond language",
  "auth.focus": "Stay in the moment.",
  "auth.understand": "Understand every word.",
  "auth.intro": "Turn Korean and English lectures into Chinese notes.",
  "auth.explore": "Follow the transcript, understand the ideas, and explore the evidence.",
  "auth.sample": "Product preview · Not live captions",
  "auth.captions": "Bilingual captions",
  "auth.knowledge": "Knowledge capture",
  "auth.evidence": "Evidence-based Q&A",
  "auth.footer": "From speech to understanding. From lectures to knowledge.",
  "auth.private": "Your private learning space",
  "auth.welcome": "Welcome back",
  "auth.continue": "Sign in to ClassBridge to continue learning.",
  "auth.username": "Username",
  "auth.password": "Password",
  "auth.busy": "Signing in…",
  "auth.submit": "Open Workspace",
  "auth.failed": "Sign-in failed. Check your credentials and network connection.",
  "auth.registration": "Existing private accounts only. An administrator must initialize accounts on the server. Public registration is disabled.",
  "auth.demo": "New here? Create a demo session after signing in. Demos do not call paid APIs.",
  "common.title": "ClassBridge · Speech Workspace",
  "common.error": "Something went wrong. Please try again.",
  "settings.language": "Interface language",
  "settings.languageDescription": "Changes the interface language only. Speech recognition and subtitle translation languages remain unchanged.",
  "settings.languageSaving": "Saving interface language…",
  "settings.languageFailed": "The interface language is applied locally but could not be saved to your account. Select a language again to retry.",
  "navigation.workspace": "Workspace navigation",
  "navigation.brand": "ClassBridge Workspace",
  "navigation.close": "Close navigation",
  "navigation.open": "Open navigation",
  "navigation.main": "Main navigation",
  "navigation.expand": "Expand sidebar",
  "navigation.collapse": "Collapse sidebar",
  "navigation.private": "Private space",
  "navigation.privateWorkspace": "Private workspace",
  "navigation.privacy": "Audio and documents are private by default",
  "navigation.networkHint": "Browser network status; does not indicate a speech recognition connection",
  "navigation.online": "Online",
  "navigation.offline": "Offline",
  "navigation.light": "Switch to light mode",
  "navigation.dark": "Switch to dark mode",
  "navigation.logout": "Sign out",
  "navigation.live": "Live Session",
  "sessions.new": "New Session",
  "sessions.recent": "Recent sessions",
  "sessions.empty": "No saved sessions yet",
  "sessions.demoSuffix": " · Demo",
  "common.dismiss": "Dismiss notification",
  "common.opening": "Opening your workspace…",
  "common.loadingSession": "Loading session…",
  "common.offline": "You are offline. Saved content is safe. Live capture requires a server connection.",
  "navigation.home": "Workspace",
  "navigation.library": "Library",
  "navigation.settings": "Settings",
  "sessions.count": "{count} sessions",
  "sessions.count_one": "{count} session",
};
export const ko: Locale = {
  ...sessionExtraKo,
  ...sessionDetailsKo,
  ...settingsHelpKo,
  ...sessionToolsKo,
  ...asrModelsKo,
  ...diagnosticsKo,
  ...captureKo,
  ...stageKo,
  ...settingsKo,
  ...libraryKo,
  ...foldersKo,
  ...homeKo,
  ...newSessionKo,
  ...chatKo,
  "auth.brand": "음성 이해 작업 공간",
  "auth.eyebrow": "언어의 장벽을 넘어 이해하세요",
  "auth.focus": "지금 이 순간에 집중하세요.",
  "auth.understand": "모든 말을 이해하세요.",
  "auth.intro": "한국어와 영어 강의를 자연스럽게 중국어 노트로 정리하세요.",
  "auth.explore": "원문을 듣고 지식을 이해하며 근거를 바탕으로 탐구하세요.",
  "auth.sample": "제품 예시 · 실시간 자막 아님",
  "auth.captions": "이중 언어 자막",
  "auth.knowledge": "지식 축적",
  "auth.evidence": "근거 기반 질의응답",
  "auth.footer": "음성에서 이해로, 강의에서 지식으로.",
  "auth.private": "나만의 학습 공간",
  "auth.welcome": "다시 오신 것을 환영합니다",
  "auth.continue": "ClassBridge에 로그인하여 학습을 이어가세요.",
  "auth.username": "사용자 이름",
  "auth.password": "비밀번호",
  "auth.busy": "로그인 중…",
  "auth.submit": "작업 공간 열기",
  "auth.failed": "로그인하지 못했습니다. 계정 정보와 네트워크 연결을 확인해 주세요.",
  "auth.registration": "기존 개인 계정만 사용할 수 있습니다. 관리자가 서버에서 계정을 초기화해야 합니다. 공개 회원가입은 지원하지 않습니다.",
  "auth.demo": "처음 사용하시나요? 로그인 후 데모 세션을 만들어 보세요. 데모는 유료 API를 호출하지 않습니다.",
  "common.title": "ClassBridge · 음성 이해 작업 공간",
  "common.error": "작업에 실패했습니다. 다시 시도해 주세요.",
  "settings.language": "인터페이스 언어",
  "settings.languageDescription": "인터페이스 표시 언어만 변경되며, 음성 인식 및 자막 번역 언어에는 영향을 주지 않습니다.",
  "settings.languageSaving": "인터페이스 언어 저장 중…",
  "settings.languageFailed": "인터페이스 언어가 로컬에 적용되었지만 계정에 저장하지 못했습니다. 언어를 다시 선택하여 재시도해 주세요.",
  "navigation.workspace": "작업 공간 탐색",
  "navigation.brand": "ClassBridge 작업 공간",
  "navigation.close": "탐색 메뉴 닫기",
  "navigation.open": "탐색 메뉴 열기",
  "navigation.main": "주 탐색 메뉴",
  "navigation.expand": "사이드바 펼치기",
  "navigation.collapse": "사이드바 접기",
  "navigation.private": "개인 공간",
  "navigation.privateWorkspace": "개인 작업 공간",
  "navigation.privacy": "오디오와 자료는 기본적으로 비공개입니다",
  "navigation.networkHint": "브라우저 네트워크 상태이며 음성 인식 서비스 연결 상태와는 다릅니다",
  "navigation.online": "온라인",
  "navigation.offline": "오프라인",
  "navigation.light": "라이트 모드로 전환",
  "navigation.dark": "다크 모드로 전환",
  "navigation.logout": "로그아웃",
  "navigation.live": "실시간 세션",
  "sessions.new": "새 세션",
  "sessions.recent": "최근 세션",
  "sessions.empty": "저장된 세션이 없습니다",
  "sessions.demoSuffix": " · 데모",
  "common.dismiss": "알림 닫기",
  "common.opening": "작업 공간을 여는 중…",
  "common.loadingSession": "세션을 불러오는 중…",
  "common.offline": "네트워크 연결이 끊겼습니다. 저장된 내용은 유지됩니다. 실시간 음성 수집에는 서버 연결이 필요합니다.",
  "navigation.home": "작업 공간",
  "navigation.library": "자료실",
  "navigation.settings": "설정",
  "sessions.count": "세션 {count}개",
  "sessions.count_one": "세션 {count}개",
};
export const locales = { "zh-CN": zhCN, en, ko };
export function translate(language: UILanguage, key: TranslationKey, params: Record<string, string | number> = {}): string {
  const locale = locales[language] || zhCN;
  const pluralKey = `${key}_one`;
  const selected = params.count === 1 && Object.prototype.hasOwnProperty.call(zhCN, pluralKey)
    ? pluralKey as TranslationKey : key;
  const template = Object.prototype.hasOwnProperty.call(zhCN, selected)
    ? locale[selected] || zhCN[selected] : locale["common.error"];
  return template.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? ""));
}
export function formatDate(language: UILanguage, value: string | number | Date) {
  return new Intl.DateTimeFormat(language, { dateStyle: "long" }).format(new Date(value));
}
export function formatNumber(language: UILanguage, value: number) {
  return new Intl.NumberFormat(language).format(value);
}
export function formatRelative(language: UILanguage, value: number, unit: Intl.RelativeTimeFormatUnit) {
  return new Intl.RelativeTimeFormat(language, { numeric: "auto" }).format(value, unit);
}