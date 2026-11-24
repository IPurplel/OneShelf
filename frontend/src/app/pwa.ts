/**
 * The installed app's one extra: a short page for when the computer OneShelf lives on cannot be reached.
 * See `public/sw.js`, which stores nothing else. Service workers only run on a secure origin (https or
 * localhost); anywhere else this does nothing, and the app works exactly as it does in a browser tab.
 */
export async function registerOfflinePage(): Promise<void> {
  if (!window.isSecureContext || !("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  } catch {
    // Blocked by the browser or a private window: the offline page is a nicety, never a requirement.
  }
}
