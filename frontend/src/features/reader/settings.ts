export type ReaderMode = "long_strip" | "single" | "double";
export type ReaderDirection = "ltr" | "rtl" | "vertical";
export type ReaderFit = "smart" | "width" | "height" | "original";
export type ReaderBackground = "black" | "dark" | "white";

export type ReaderSettings = {
  mode: ReaderMode;
  direction: ReaderDirection;
  fit: ReaderFit;
  background: ReaderBackground;
  gap: number;
  /** §26.8: the first page stands alone, so every spread after it lines up. */
  coverAlone: boolean;
  /** §26.8: manual Shift Pairing, for a book with an extra single page somewhere in the middle. */
  shiftPairing: boolean;
};

export const DEFAULT_SETTINGS: ReaderSettings = {
  mode: "long_strip", direction: "ltr", fit: "smart", background: "black", gap: 8,
  coverAlone: true, shiftPairing: false,
};

/**
 * Settings precedence (Master §26.17): session → work → content type → global. Remembering per work is
 * ON by default, and a remembered preference is a convenience: a blocked storage read is not an error.
 */
export function loadSettings(workId: string | null, contentType: string | null): ReaderSettings {
  const keys = [workId ? `oneshelf.reader.work.${workId}` : null,
                contentType ? `oneshelf.reader.type.${contentType}` : null,
                "oneshelf.reader.global"];
  for (const key of keys) {
    if (key === null) continue;
    try {
      const stored = window.localStorage.getItem(key);
      if (stored) return { ...DEFAULT_SETTINGS, ...JSON.parse(stored) as Partial<ReaderSettings> };
    } catch {
      // Ignore: reading falls through to the next level and finally to the defaults.
    }
  }
  return DEFAULT_SETTINGS;
}

export function saveSettings(workId: string | null, settings: ReaderSettings): void {
  try {
    window.localStorage.setItem(workId ? `oneshelf.reader.work.${workId}` : "oneshelf.reader.global",
                                JSON.stringify(settings));
  } catch {
    // Remembering is optional; the session still has the setting.
  }
}
