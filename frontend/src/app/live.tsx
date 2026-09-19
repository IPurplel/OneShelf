import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

/** Every event the library publishes, plus the two the stream itself sends. */
export type LiveEvent =
  | "hello" | "resync"
  | "download.batch" | "download.job"
  | "notifications.changed" | "reader.progress"
  | "follow.changed" | "follow.releases" | "shelf.changed" | "source.session";

type Listener = (data: unknown) => void;

type LiveState = {
  /** Whether the stream is open. When it is not, screens are refreshed by polling instead. */
  connected: boolean;
  subscribe: (types: readonly LiveEvent[], listener: Listener) => () => void;
};

const LiveContext = createContext<LiveState | null>(null);

const RECONNECT_MS = 2000;
const POLL_MS = 15000;

/**
 * The live channel (Master §36, §56).
 *
 * One stream for the whole app, same-origin and cookie-carrying, carrying identifiers rather than
 * content. When it cannot be opened — an old browser, a proxy that buffers, a restart — the screens
 * that depend on it are refreshed by polling instead, so the app is never wrong, only less immediate.
 * A `resync` means the server dropped this subscriber: the answer is to re-read, never to guess what
 * was missed.
 */
export function LiveProvider({ children, pollMs = POLL_MS }: { children: ReactNode; pollMs?: number }) {
  const listeners = useRef(new Map<LiveEvent, Set<Listener>>());
  const [connected, setConnected] = useState(false);

  const dispatch = useCallback((type: LiveEvent, data: unknown) => {
    for (const listener of listeners.current.get(type) ?? []) listener(data);
  }, []);

  const subscribe = useCallback((types: readonly LiveEvent[], listener: Listener) => {
    for (const type of types) {
      const set = listeners.current.get(type) ?? new Set<Listener>();
      set.add(listener);
      listeners.current.set(type, set);
    }
    return () => {
      for (const type of types) listeners.current.get(type)?.delete(listener);
    };
  }, []);

  useEffect(() => {
    if (typeof EventSource === "undefined") return;           // polling carries the app instead
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let live = true;

    const open = () => {
      if (!live) return;
      source = new EventSource("/api/events");
      source.addEventListener("hello", () => setConnected(true));
      for (const type of ["download.batch", "download.job", "notifications.changed", "reader.progress",
                          "follow.changed", "follow.releases", "shelf.changed",
                          "source.session"] as LiveEvent[]) {
        source.addEventListener(type, (event) => {
          dispatch(type, parse((event as MessageEvent).data));
        });
      }
      // The server ends the stream after a resync; re-read, then open a fresh one.
      source.addEventListener("resync", (event) => {
        dispatch("resync", parse((event as MessageEvent).data));
        setConnected(false);
        source?.close();
        retry = setTimeout(open, RECONNECT_MS);
      });
      source.onerror = () => {
        setConnected(false);
        source?.close();
        retry = setTimeout(open, RECONNECT_MS);
      };
    };

    open();
    return () => {
      live = false;
      if (retry !== null) clearTimeout(retry);
      source?.close();
    };
  }, [dispatch]);

  // While the stream is down, the screens listening for an event are told to re-read on a timer.
  useEffect(() => {
    if (connected) return;
    const timer = setInterval(() => {
      for (const [type, set] of listeners.current) {
        for (const listener of set) listener({ polled: true, type });
      }
    }, pollMs);
    return () => clearInterval(timer);
  }, [connected, pollMs]);

  const value = useMemo(() => ({ connected, subscribe }), [connected, subscribe]);
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

/** Re-read when the library says something changed. The handler is called, never trusted with state. */
export function useLive(types: readonly LiveEvent[], onChange: () => void): { connected: boolean } {
  const context = useContext(LiveContext);
  const handler = useRef(onChange);
  handler.current = onChange;

  useEffect(() => {
    if (context === null) return;
    return context.subscribe([...types, "resync"], () => handler.current());
    // The list is stable per screen; spreading it here keeps the subscription from churning.
  }, [context, types.join(",")]);          // eslint-disable-line react-hooks/exhaustive-deps

  return { connected: context?.connected ?? false };
}

function parse(data: unknown): unknown {
  if (typeof data !== "string") return data;
  try {
    return JSON.parse(data);
  } catch {
    return {};
  }
}
