import { STRINGS } from "./strings";
import type { Language } from "./strings";

/** A language code in the selected UI locale, falling back to the original code. */
export function languageName(code: string, locale: Language): string {
  if (code.toLowerCase() === "und") return STRINGS[locale]["language.unknown"];
  try {
    return new Intl.DisplayNames([locale], { type: "language", fallback: "none" }).of(code) ?? code;
  } catch {
    return code;
  }
}
