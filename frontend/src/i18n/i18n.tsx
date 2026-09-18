import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { DIRECTION, LANGUAGES, STRINGS } from "./strings";
import type { Language, StringKey } from "./strings";

type I18n = {
  language: Language;
  direction: "ltr" | "rtl";
  t: (key: StringKey, values?: Record<string, string | number>) => string;
  setLanguage: (language: Language) => void;
  toggleLanguage: () => void;
};

const I18nContext = createContext<I18n | null>(null);
const STORAGE_KEY = "oneshelf.language";

function initialLanguage(preferred?: Language): Language {
  if (preferred) return preferred;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored && (LANGUAGES as string[]).includes(stored)) return stored as Language;
  } catch {
    // Private windows and blocked storage are normal; fall through to the browser's preference.
  }
  return navigator.language?.startsWith("ar") ? "ar" : "en";
}

export function I18nProvider({ children, language: preferred }: { children: ReactNode; language?: Language }) {
  const [language, setLanguageState] = useState<Language>(() => initialLanguage(preferred));
  const direction = DIRECTION[language];

  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = direction;
  }, [language, direction]);

  const setLanguage = useCallback((next: Language) => {
    setLanguageState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // A remembered language is a convenience, never a requirement.
    }
  }, []);

  const value = useMemo<I18n>(() => ({
    language,
    direction,
    setLanguage,
    toggleLanguage: () => setLanguage(language === "en" ? "ar" : "en"),
    t: (key, values) => {
      const template = STRINGS[language][key] ?? STRINGS.en[key] ?? key;
      if (!values) return template;
      return Object.entries(values).reduce(
        (text, [name, replacement]) => text.replaceAll(`{${name}}`, String(replacement)),
        template as string,
      );
    },
  }), [language, direction, setLanguage]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const context = useContext(I18nContext);
  if (context === null) throw new Error("useI18n must be used inside I18nProvider");
  return context;
}
