import { ApiError } from "@/api/client";

import { sanitiseDocument, stripTags } from "./epub";
import type { Epub } from "./epub";

/**
 * A text reading unit (plugin API 1.2) presented in the Book Reader's own shape, so it reads, resumes,
 * bookmarks, highlights and searches exactly as an EPUB does (Master §26.22).
 *
 * The server has already reduced the source's markup to an allowlist and split it into sections; it is
 * sanitised once more here, with no resources at all, and still only ever rendered in the empty-sandbox
 * frame (§27, ledger K3). The unit's own language decides its direction, never the interface language.
 */

export type TextSection = { title: string | null; html: string; characters: number };

export type TextUnitPayload = {
  reading_unit_id: string;
  origin: "local" | "online";
  title: string | null;
  language: string | null;
  direction: "ltr" | "rtl";
  sections: TextSection[];
};

export type TextBook = Epub & { direction: "ltr" | "rtl" };

export async function fetchTextUnit(unitId: string): Promise<TextUnitPayload> {
  const response = await fetch(`/api/reader/units/${unitId}/text`, { credentials: "same-origin" });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload === null) {
    throw new ApiError(response.status, payload?.error?.code ?? "TEXT_NOT_AVAILABLE",
                       payload?.error?.message ?? "This text is not available.");
  }
  return payload as TextUnitPayload;
}

/** A section without a heading of its own is named after its unit and place: "Chapter 7 · 2". */
function sectionTitle(payload: TextUnitPayload, index: number): string {
  const title = payload.sections[index]?.title;
  if (title) return title;
  return payload.title ? `${payload.title} · ${index + 1}` : String(index + 1);
}

export function textBook(payload: TextUnitPayload): TextBook {
  const spine = payload.sections.map((section, index) => ({
    id: `section-${index + 1}`,
    href: `section-${index + 1}`,
    title: sectionTitle(payload, index),
    characters: section.characters,
  }));
  return {
    title: payload.title ?? "",
    language: payload.language,
    creator: null,
    direction: payload.direction === "rtl" ? "rtl" : "ltr",
    spine,
    characters: spine.reduce((total, item) => total + item.characters, 0),
    chapter: async (index: number) => {
      const section = payload.sections[index];
      if (section === undefined) throw new Error(`no section ${index + 1}`);
      return { href: spine[index]?.href ?? "", html: sanitiseDocument(section.html, () => null), text: stripTags(section.html) };
    },
    close: () => {},
  };
}

export async function openTextUnit(unitId: string): Promise<TextBook> {
  return textBook(await fetchTextUnit(unitId));
}
