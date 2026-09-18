import { useCallback, useEffect, useState } from "react";

export type Bookmark = { chapter: number; label: string };
export type Highlight = { id: string; chapter: number; text: string };

type Marks = { bookmarks: Bookmark[]; highlights: Highlight[] };

const EMPTY: Marks = { bookmarks: [], highlights: [] };

/**
 * Bookmarks and highlights for one book (Master §26.22). v1 keeps exactly these two — no notes, no
 * drawing — and they are a per-viewer convenience, so blocked storage is not an error.
 */
export function useBookMarks(unitId: string) {
  const key = `oneshelf.book.${unitId}`;
  const [marks, setMarks] = useState<Marks>(EMPTY);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(key);
      setMarks(stored ? { ...EMPTY, ...JSON.parse(stored) as Partial<Marks> } : EMPTY);
    } catch {
      setMarks(EMPTY);
    }
  }, [key]);

  const persist = useCallback((next: Marks) => {
    setMarks(next);
    try {
      window.localStorage.setItem(key, JSON.stringify(next));
    } catch {
      // Keeping them for this session is better than refusing to bookmark at all.
    }
  }, [key]);

  const addBookmark = useCallback((bookmark: Bookmark) => {
    setMarks((current) => {
      if (current.bookmarks.some((entry) => entry.chapter === bookmark.chapter)) return current;
      const next = { ...current, bookmarks: [...current.bookmarks, bookmark] };
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch { /* session-only is fine */ }
      return next;
    });
  }, [key]);

  const addHighlight = useCallback((highlight: Highlight) => {
    persist({ ...marks, highlights: [...marks.highlights, highlight] });
  }, [marks, persist]);

  const remove = useCallback((chapter: number) => {
    persist({ ...marks, bookmarks: marks.bookmarks.filter((entry) => entry.chapter !== chapter) });
  }, [marks, persist]);

  return { ...marks, addBookmark, addHighlight, remove };
}
