import { MOBILE_QUERY } from "@/app/useMediaQuery";

type Listener = (event: MediaQueryListEvent) => void;

/** jsdom has no layout engine, so tests declare which viewport they are describing. */
export function setViewport(kind: "desktop" | "mobile") {
  const listeners = new Set<Listener>();
  window.matchMedia = ((query: string) => ({
    media: query,
    matches: kind === "mobile" && query === MOBILE_QUERY,
    onchange: null,
    addEventListener: (_: string, listener: Listener) => listeners.add(listener),
    removeEventListener: (_: string, listener: Listener) => listeners.delete(listener),
    addListener: (listener: Listener) => listeners.add(listener),
    removeListener: (listener: Listener) => listeners.delete(listener),
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
