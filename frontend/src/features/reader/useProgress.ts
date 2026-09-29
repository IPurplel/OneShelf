import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, api } from "@/api/client";

export type ProgressState = { read_state: string; fraction: number | null; locator: unknown; revision: number };
type Position = { fraction: number; locator: unknown };
const DEBOUNCE_MS = 1200;

/** Each mounted unit owns its queue and revision, including writes that finish after navigation. */
function progressSession(unitId: string) {
  const path = `/api/reader/units/${unitId}/progress`;
  let revision = 0;
  let ready = false;
  let writing = false;
  let due = false;
  let pending: Position | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let initial: Promise<ProgressState> | null = null;
  const clearTimer = () => { if (timer !== null) clearTimeout(timer); timer = null; };

  const send = async () => {
    if (!ready || writing || !due || pending === null) return;
    const payload = pending;
    pending = null;
    due = false;
    writing = true;
    try {
      const state = await api.post<ProgressState>(path, { ...payload, revision });
      revision = state.revision;
    } catch (error) {
      if (error instanceof ApiError && error.code === "STALE_PROGRESS") {
        // Another tab wins. Never replay a position recorded against the superseded revision.
        ready = false;
        try { revision = (await api.get<ProgressState>(path)).revision; ready = true; }
        catch { initial = null; /* Retry the revision on the next explicit flush. */ }
        pending = null;
        due = false;
        clearTimer();
      } else {
        // Keep the latest position for a later explicit flush; do not spin on an offline library.
        pending ??= payload;
        due = false;
      }
    } finally {
      writing = false;
    }
    void send();
  };
  const load = (): Promise<ProgressState> => initial ??= api.get<ProgressState>(path).then((state) => {
      revision = state.revision;
      ready = true;
      void send();
      return state;
    }).catch((error) => { initial = null; throw error; });
  const flush = () => {
    clearTimer();
    due = true;
    if (!ready && pending !== null) void load().catch(() => {});
    else void send();
  };
  return {
    load,
    record: (fraction: number, locator: unknown) => {
      pending = { fraction, locator };
      clearTimer();
      timer = setTimeout(flush, DEBOUNCE_MS);
    },
    flush,
    setRevision: (value: number) => { revision = value; },
  };
}

/** Debounced, serialized saves; opening/resuming a reader never writes a position. */
export function useProgress(unitId: string) {
  const session = useMemo(() => progressSession(unitId), [unitId]);
  const [loaded, setLoaded] = useState<{ session: typeof session; state: ProgressState } | null>(null);
  useEffect(() => {
    let live = true;
    void session.load().then((state) => { if (live) setLoaded({ session, state }); }).catch(() => {});
    const onHidden = () => { if (document.visibilityState === "hidden") session.flush(); };
    document.addEventListener("visibilitychange", onHidden);
    window.addEventListener("pagehide", session.flush);
    return () => {
      live = false;
      document.removeEventListener("visibilitychange", onHidden);
      window.removeEventListener("pagehide", session.flush);
      session.flush();
    };
  }, [session]);
  const record = useCallback((fraction: number, locator: unknown) => session.record(fraction, locator), [session]);
  return { record, flush: session.flush, setRevision: session.setRevision,
           stored: loaded?.session === session ? loaded.state : null };
}
