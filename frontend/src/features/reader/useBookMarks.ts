import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/api/client";
import { newOperationId } from "@/lib/operationId";

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
  const owner = useMemo(() => ({ live: true }), [unitId]);
  const [state, setState] = useState<{ owner: typeof owner; marks: Marks }>({ owner, marks: EMPTY });
  const marks = state.owner === owner ? state.marks : EMPTY;
  const setMarks = useCallback((update: Marks | ((current: Marks) => Marks)) => {
    if (!owner.live) return;
    setState((current) => ({ owner, marks: typeof update === "function"
      ? update(current.owner === owner ? current.marks : EMPTY) : update }));
  }, [owner]);

  const reload = useCallback(async () => {
    try {
      setMarks(await api.get<Marks>(`/api/reader/units/${unitId}/marks`));
    } catch {
      setMarks(EMPTY);        // a library that cannot be reached shows no marks rather than wrong ones
    }
  }, [unitId, setMarks]);

  useEffect(() => {
    owner.live = true;
    void reload();
    return () => { owner.live = false; };
  }, [owner, reload]);

  const addBookmark = useCallback(async (locator: Locator, label: string | null,
                                   operationId: string = newOperationId()) => {
    const made = await api.post<Bookmark>(`/api/reader/units/${unitId}/bookmarks`,
      { locator, label, operation_id: operationId });
    setMarks((current) => current.bookmarks.some((entry) => entry.id === made.id)
      ? current : { ...current, bookmarks: [...current.bookmarks, made] });
  }, [unitId, setMarks]);

  const addHighlight = useCallback(async (locator: Locator, text: string,
                                    operationId: string = newOperationId()) => {
    const made = await api.post<Highlight>(`/api/reader/units/${unitId}/highlights`,
      { locator, text, operation_id: operationId });
    setMarks((current) => current.highlights.some((entry) => entry.id === made.id)
      ? current : { ...current, highlights: [...current.highlights, made] });
  }, [unitId, setMarks]);

  const removeBookmark = useCallback(async (id: string) => {
    await api.delete(`/api/reader/bookmarks/${id}`);
    setMarks((current) => ({ ...current, bookmarks: current.bookmarks.filter((entry) => entry.id !== id) }));
  }, [setMarks]);

  const removeHighlight = useCallback(async (id: string) => {
    await api.delete(`/api/reader/highlights/${id}`);
    setMarks((current) => ({ ...current, highlights: current.highlights.filter((entry) => entry.id !== id) }));
  }, [setMarks]);

  return { ...marks, addBookmark, addHighlight, removeBookmark, removeHighlight, reload };
}
