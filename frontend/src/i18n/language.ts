/** A language code as a person reads it, in their own locale — and the code itself when it cannot be. */
export function languageName(code: string): string {
  try {
    return new Intl.DisplayNames(undefined, { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}
