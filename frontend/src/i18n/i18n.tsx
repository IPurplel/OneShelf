import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { DIRECTION, LANGUAGES, STRINGS } from "./strings";
import type { Language, StringKey } from "./strings";
import { apiErrorText } from "./apiErrors";

/** A counted phrase: every `<base>.other` key names one, with `.zero/.one/.two/.few/.many` beside it as needed. */
export type PluralKey = { [K in StringKey]: K extends `${infer Base}.other` ? Base : never }[StringKey];

type Values = Record<string, string | number>;

type I18n = {
  language: Language;
  direction: "ltr" | "rtl";
  t: (key: StringKey, values?: Values) => string;
  /**
   * The form of a counted phrase this language needs for `count` (Arabic has six), with `{count}` written
   * in the language's own digits. Falls back to `<base>.other`, then to English.
   */
  tn: (base: PluralKey, count: number, values?: Values) => string;
  /** What a failed request means for the person, in their language (see apiErrors.ts). */
  errorText: (error: unknown) => string;
  setLanguage: (language: Language) => void;
  toggleLanguage: () => void;
};

const fill = (template: string, values?: Values) => !values ? template : Object.entries(values).reduce(
  (text, [name, replacement]) => text.replaceAll(`{${name}}`, String(replacement)), template);

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

  // Load the Arabic faces before anything Arabic is painted, so no one ever sees a row of boxes.
  useEffect(() => {
    if (typeof document === "undefined" || !("fonts" in document)) return;
    const faces = ['400 16px "Noto Naskh Arabic"', '600 16px "Noto Naskh Arabic"'];
    for (const face of faces) {
      void document.fonts.load(face, "ا").catch(() => undefined);
    }
  }, []);

  const setLanguage = useCallback((next: Language) => {
    setLanguageState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // A remembered language is a convenience, never a requirement.
    }
  }, []);

  const value = useMemo<I18n>(() => {
    const t = (key: StringKey, values?: Values) =>
      fill((STRINGS[language][key] ?? STRINGS.en[key] ?? key) as string, values);
    const rules = new Intl.PluralRules(language);
    const numbers = new Intl.NumberFormat(language);
    const table = STRINGS[language] as Record<string, string>;
    const english = STRINGS.en as Record<string, string>;
    const tn = (base: PluralKey, count: number, values?: Values) => {
      const exact = `${base}.${rules.select(count)}`;
      const template = table[exact] ?? table[`${base}.other`] ?? english[`${base}.${new Intl.PluralRules("en").select(count)}`]
        ?? english[`${base}.other`] ?? base;
      return fill(template, { count: numbers.format(count), ...values });
    };
    return {
      language,
      direction,
      setLanguage,
      toggleLanguage: () => setLanguage(language === "en" ? "ar" : "en"),
      t,
      tn,
      errorText: (error: unknown) => apiErrorText(error, language, t),
    };
  }, [language, direction, setLanguage]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const context = useContext(I18nContext);
  if (context === null) throw new Error("useI18n must be used inside I18nProvider");
  return context;
}
