import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "./client";

export type Resource<T> = { data: T | null; error: string | null; loading: boolean; reload: () => void };

/** One small hook for read-only screens: data, a plain error message, and a way to try again. */
export function useResource<T>(path: string, query?: Record<string, string | number | boolean | undefined>): Resource<T> {
  const key = JSON.stringify(query ?? {});
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({
    data: null, error: null, loading: true,
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setState((current) => ({ ...current, loading: true }));
    api.get<T>(path, query)
      .then((data) => { if (live) setState({ data, error: null, loading: false }); })
      .catch((error: unknown) => {
        if (!live) return;
        const message = error instanceof ApiError ? error.message : "offline";
        setState({ data: null, error: message, loading: false });
      });
    return () => { live = false; };
  }, [path, key, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, reload };
}
