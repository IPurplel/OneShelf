/** UI strings. Arabic and English are peers: the UI direction follows the language (Master §2.3). */
export const STRINGS = {
  en: {
    "app.name": "OneShelf",
    "app.tagline": "Your stories, one library.",
    "nav.primary": "Primary",
    "nav.home": "Home",
    "nav.search": "Search",
    "nav.shelf": "My Shelf",
    "nav.following": "Following",
    "nav.downloads": "Downloads",
    "nav.sources": "Sources",
    "nav.settings": "Settings",
    "nav.more": "More",
    "header.notifications": "Notifications",
    "header.attention": "Needs attention",
    "header.language": "العربية",
    "skip.content": "Skip to content",
    "state.loading": "Loading…",
    "state.offline": "OneShelf is not responding. It may be restarting.",
  },
  ar: {
    "app.name": "وَنْ شِلْف",
    "app.tagline": "حكاياتك، مكتبة واحدة.",
    "nav.primary": "الرئيسي",
    "nav.home": "الرئيسية",
    "nav.search": "البحث",
    "nav.shelf": "رفّي",
    "nav.following": "المتابَعة",
    "nav.downloads": "التنزيلات",
    "nav.sources": "المصادر",
    "nav.settings": "الإعدادات",
    "nav.more": "المزيد",
    "header.notifications": "الإشعارات",
    "header.attention": "يحتاج انتباهك",
    "header.language": "English",
    "skip.content": "تخطَّ إلى المحتوى",
    "state.loading": "جارٍ التحميل…",
    "state.offline": "لا يستجيب وَنْ شِلْف. ربما تُعاد تشغيله.",
  },
} as const;

export type Language = keyof typeof STRINGS;
export type StringKey = keyof (typeof STRINGS)["en"];
export const LANGUAGES: Language[] = ["en", "ar"];
export const DIRECTION: Record<Language, "ltr" | "rtl"> = { en: "ltr", ar: "rtl" };
