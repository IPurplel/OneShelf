export type ReaderMode = "long_strip" | "single" | "double";
export type BookFont = "serif" | "sans";
export type BookSize = "smaller" | "normal" | "larger" | "largest";
export type BookSpacing = "tight" | "normal" | "loose";
export type BookMargins = "narrow" | "normal" | "wide";
export type BookTheme = "paper" | "sepia" | "dark";
export type PdfFit = "width" | "page" | "custom";
export type ReaderDirection = "ltr" | "rtl" | "vertical";
export type ReaderFit = "smart" | "width" | "height" | "original";
export type ReaderBackground = "black" | "dark" | "white";
export type ReaderControls = "smart" | "minimal";

export type ReaderSettings = {
  mode: ReaderMode;
  direction: ReaderDirection;
  fit: ReaderFit;
  background: ReaderBackground;
  /** §26.3: Smart shows the controls on interaction; Minimal keeps them away until summoned. */
  controls: ReaderControls;
  gap: number;
  /** §26.8: the first page stands alone, so every spread after it lines up. */
  coverAlone: boolean;
  /** §26.8: manual Shift Pairing, for a book with an extra single page somewhere in the middle. */
  shiftPairing: boolean;
  /** §26.22a: how a book reads. Applied by OneShelf's own stylesheet, never by the book. */
  bookFont: BookFont;
  bookSize: BookSize;
  bookSpacing: BookSpacing;
  bookMargins: BookMargins;
  bookTheme: BookTheme;
  /** §26.22b: how a PDF page is scaled. */
  pdfFit: PdfFit;
  pdfZoom: number;
};

export const DEFAULT_SETTINGS: ReaderSettings = {
  mode: "long_strip", direction: "ltr", fit: "smart", background: "black", controls: "smart", gap: 8,
  coverAlone: true, shiftPairing: false,
  bookFont: "serif", bookSize: "normal", bookSpacing: "normal", bookMargins: "normal", bookTheme: "paper",
  pdfFit: "width", pdfZoom: 1,
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

/** The numbers behind the named sizes, kept here so the frame and the panel cannot disagree. */
export const BOOK_TYPE = {
  font: { serif: 'Georgia, "Noto Naskh Arabic", serif', sans: 'system-ui, "Noto Naskh Arabic", sans-serif' },
  size: { smaller: 16, normal: 18, larger: 21, largest: 24 },
  spacing: { tight: 1.45, normal: 1.7, loose: 2 },
  margins: { narrow: "4vh 4vw", normal: "4vh 6vw", wide: "4vh 12vw" },
  theme: {
    paper: { background: "#fffdf8", ink: "#1c1b18" },
    sepia: { background: "#f4ecd8", ink: "#3a2f21" },
    dark: { background: "#16181a", ink: "#d9d6cf" },
  },
} as const;
