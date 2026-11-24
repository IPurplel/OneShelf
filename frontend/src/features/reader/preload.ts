/** The reader's code, loaded on demand: the reader route and the preload below share this one import. */
export const loadReader = () => import("./ReadRoute");

/** Fetch the reader's code while a Work is on screen, so pressing Read does not wait for its download. */
export function preloadReader(): void {
  const start = () => { void loadReader().catch(() => {}); };
  if (typeof window.requestIdleCallback === "function") window.requestIdleCallback(start, { timeout: 2000 });
  else window.setTimeout(start, 200);
}
