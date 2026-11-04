/** UI strings; the TV's language picks Arabic (RTL) or English. */

export type Language = "ar" | "en";

export interface Strings {
  appName: string;
  statusReady: string;
  statusWaiting: string;
  statusConnected: string;
  statusOffline: string;
  previewIdle: string;
  infoTitle: string;
  infoText: string;
  playCamera: string;
  help: string;
  exit: string;
  live: string;
  helpTitle: string;
  helpHome: string[];
  helpPlayer: string[];
  close: string;
  camPrev: string;
  camNext: string;
  camFit: string;
}

const STRINGS: Record<Language, Strings> = {
  en: {
    appName: "Samstream",
    statusReady: "Ready",
    statusWaiting: "Waiting for Home Assistant",
    statusConnected: "Connected to Home Assistant",
    statusOffline: "Home Assistant is not reachable",
    previewIdle: "No camera playing",
    infoTitle: "Your cameras on the big screen",
    infoText:
      "When the doorbell rings, Home Assistant opens the camera here, then takes you back to what you were watching.",
    playCamera: "Play camera",
    help: "Help",
    exit: "Exit",
    live: "LIVE",
    helpTitle: "Remote control",
    helpHome: ["◀ ▶  Move between buttons", "OK  Select", "BACK  Close Samstream"],
    helpPlayer: [
      "◀ ▶  Previous / next camera",
      "1–9  Jump to a camera",
      "▲ ▼  Fit, fill (crop) or stretch",
      "OK  Restart the stream",
      "INFO / green  Show this help",
      "BACK  Back to the home screen",
    ],
    close: "Close",
    camPrev: "Previous",
    camNext: "Next",
    camFit: "Fit",
  },
  ar: {
    appName: "Samstream",
    statusReady: "جاهز",
    statusWaiting: "في انتظار Home Assistant",
    statusConnected: "متصل بـ Home Assistant",
    statusOffline: "تعذّر الوصول إلى Home Assistant",
    previewIdle: "لا توجد كاميرا قيد التشغيل",
    infoTitle: "كاميراتك على الشاشة الكبيرة",
    infoText:
      "عند رنين جرس الباب يفتح Home Assistant الكاميرا هنا، ثم يعيدك إلى ما كنت تشاهده.",
    playCamera: "تشغيل الكاميرا",
    help: "المساعدة",
    exit: "خروج",
    live: "مباشر",
    helpTitle: "جهاز التحكم",
    helpHome: ["◀ ▶  التنقل بين الأزرار", "OK  اختيار", "BACK  إغلاق Samstream"],
    helpPlayer: [
      "◀ ▶  الكاميرا السابقة / التالية",
      "1–9  اختيار كاميرا",
      "▲ ▼  ملاءمة أو ملء (قص) أو تمديد",
      "OK  إعادة تشغيل البث",
      "INFO / الأخضر  إظهار هذه المساعدة",
      "BACK  العودة إلى الشاشة الرئيسية",
    ],
    close: "إغلاق",
    camPrev: "السابقة",
    camNext: "التالية",
    camFit: "الملاءمة",
  },
};

/** HA's choice wins; "auto" follows the TV's locale. */
export function resolveLanguage(setting: "auto" | Language, locale: string | undefined): Language {
  return setting === "auto" ? detectLanguage(locale) : setting;
}

/** `ar_AE`, `ar-EG`, `ar` → Arabic; anything else → English. */
export function detectLanguage(locale: string | undefined): Language {
  return (locale ?? "").toLowerCase().startsWith("ar") ? "ar" : "en";
}

export function strings(language: Language): Strings {
  return STRINGS[language];
}

/** Set `lang`/`dir` on the document so logical CSS properties flip for RTL. */
export function applyLanguage(root: HTMLElement, language: Language): void {
  root.lang = language;
  root.dir = language === "ar" ? "rtl" : "ltr";
}
