import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./client";
import { useI18n } from "@/i18n/i18n";
import { apiErrorText } from "@/i18n/apiErrors";

export type Resource<T> = { data: T | null; error: string | null; loading: boolean; reload: () => void };

/**
 * One small hook for read-only screens: data, a plain error message, and a way to try again.
 *
 * `skip` asks nothing, for a screen whose parent already holds the same resource: it answers empty and
 * idle instead, so the same request is never sent twice for one screen.
 */
export function useResource<T>(path: string, query?: Record<string, string | number | boolean | undefined>,
                               options?: { skip?: boolean }): Resource<T> {
  const skip = options?.skip ?? false;
  const { language, t } = useI18n();
  const key = JSON.stringify(query ?? {});
  const [attempt, setAttempt] = useState(0);
  const identity = `${path}\u0000${key}`;
  const requestKey = `${identity}\u0000${attempt}`;
  const current = useRef({ key: requestKey, identity, generation: 0, preserve: false });
  if (current.current.key !== requestKey) {
    current.current = { key: requestKey, identity, generation: current.current.generation + 1,
      preserve: current.current.identity === identity };
  }
  const generation = current.current.generation;
  const preserve = current.current.preserve;
  const [state, setState] = useState<{ identity: string; generation: number; data: T | null; error: string | null; loading: boolean }>({
    identity, generation, data: null, error: null, loading: true,
  });

  useEffect(() => {
    if (skip) return;
    let live = true;
    setState(previous => ({ identity, generation,
      data: preserve && previous.identity === identity ? previous.data : null,
      error: null, loading: true }));
    api.get<T>(path, query)
      .then((data) => {
        if (live && current.current.generation === generation)
          setState({ identity, generation, data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (!live || current.current.generation !== generation) return;
        const message = apiErrorText(error, language, t);
        setState({ identity, generation, data: null, error: message, loading: false });
      });
    return () => { live = false; };
  }, [path, key, attempt, language, skip]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  if (skip) return { data: null, error: null, loading: false, reload };
  const visible = state.generation === generation ? state
    : { data: preserve && state.identity === identity ? state.data : null, error: null, loading: true };
  return { ...visible, reload };
}
