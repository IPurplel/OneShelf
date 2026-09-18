import { useCallback, useEffect, useRef } from "react";

import { ApiError, api } from "@/api/client";

export type ProgressState = { read_state: string; fraction: number | null; locator: unknown; revision: number };

const DEBOUNCE_MS = 1200;

/**
 * Progress writes (Master §26.11, §26.23).
 *
 * Writes are debounced while reading and force-flushed when the unit changes, the tab is hidden, or the
 * reader exits. Each write carries the revision this tab last saw, so a stale tab is rejected by the
 * backend instead of quietly undoing newer progress.
 */
export function useProgress(unitId: string) {
  const revision = useRef(0);
  const pending = useRef<{ fraction: number; locator: unknown } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const send = useCallback(async () => {
    const payload = pending.current;
    if (payload === null) return;
    pending.current = null;
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    try {
      const state = await api.post<ProgressState>(`/api/reader/units/${unitId}/progress`, {
        fraction: payload.fraction, locator: payload.locator, revision: revision.current,
      });
      revision.current = state.revision;
    } catch (error) {
      // A rejected stale write is the system working: re-read the revision and let the newer tab win.
      if (error instanceof ApiError && error.code === "STALE_PROGRESS") {
        try {
          const current = await api.get<ProgressState>(`/api/reader/units/${unitId}/progress`);
          revision.current = current.revision;
        } catch {
          // Leave the revision alone; the next write will be rejected again rather than clobbering.
        }
      }
    }
  }, [unitId]);

  const record = useCallback((fraction: number, locator: unknown) => {
    pending.current = { fraction, locator };
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(() => void send(), DEBOUNCE_MS);
  }, [send]);

  const flush = useCallback(() => { void send(); }, [send]);

  useEffect(() => {
    const onHidden = () => { if (document.visibilityState === "hidden") flush(); };
    document.addEventListener("visibilitychange", onHidden);
    window.addEventListener("pagehide", flush);
    return () => {
      document.removeEventListener("visibilitychange", onHidden);
      window.removeEventListener("pagehide", flush);
      flush();                                   // leaving the reader is a flush point too
    };
  }, [flush]);

  const setRevision = useCallback((value: number) => { revision.current = value; }, []);

  return { record, flush, setRevision };
}
