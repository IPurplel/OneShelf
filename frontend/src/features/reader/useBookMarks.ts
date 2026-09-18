import { useCallback, useEffect, useState } from "react";

import { api } from "@/api/client";

/** Where a mark is: `{chapter}` for a book's spine, `{page}` for a PDF, plus offsets for a highlight. */
export type Locator = { chapter?: number; page?: number; start?: number; end?: number };

export type Bookmark = { id: string; locator: Locator; label: string | null; created_at: string };
export type Highlight = { id: string; locator: Locator; text: string; colour: string; created_at: string };

type Marks = { bookmarks: Bookmark[]; highlights: Highlight[] };

const EMPTY: Marks = { bookmarks: [], highlights: [] };

/**
 * Bookmarks and highlights for one Reading Unit (Master §26.22).
 *
 * They are library state, not browser state: they are kept in OneShelf's own database, so they survive a
 * cleared browser, reach every device that reaches the library, and travel in a Library Backup. v1 keeps
 * exactly these two — no notes, no drawing (§49).
 */
export function useBookMarks(unitId: string) {
  const [marks, setMarks] = useState<Marks>(EMPTY);

  const reload = useCallback(async () => {
    try {
      setMarks(await api.get<Marks>(`/api/reader/units/${unitId}/marks`));
    } catch {
      setMarks(EMPTY);        // a library that cannot be reached shows no marks rather than wrong ones
    }
  }, [unitId]);

  useEffect(() => { void reload(); }, [reload]);

  const addBookmark = useCallback(async (locator: Locator, label: string | null) => {
    const made = await api.post<Bookmark>(`/api/reader/units/${unitId}/bookmarks`, { locator, label });
    setMarks((current) => current.bookmarks.some((entry) => entry.id === made.id)
      ? current : { ...current, bookmarks: [...current.bookmarks, made] });
  }, [unitId]);

  const addHighlight = useCallback(async (locator: Locator, text: string) => {
    const made = await api.post<Highlight>(`/api/reader/units/${unitId}/highlights`, { locator, text });
    setMarks((current) => ({ ...current, highlights: [...current.highlights, made] }));
  }, [unitId]);

  const removeBookmark = useCallback(async (id: string) => {
    await api.delete(`/api/reader/bookmarks/${id}`);
    setMarks((current) => ({ ...current, bookmarks: current.bookmarks.filter((entry) => entry.id !== id) }));
  }, []);

  const removeHighlight = useCallback(async (id: string) => {
    await api.delete(`/api/reader/highlights/${id}`);
    setMarks((current) => ({ ...current, highlights: current.highlights.filter((entry) => entry.id !== id) }));
  }, []);

  return { ...marks, addBookmark, addHighlight, removeBookmark, removeHighlight, reload };
}
