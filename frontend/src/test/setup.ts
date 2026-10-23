import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

import { setViewport } from "./viewport";

// jsdom has no object URLs; the reader creates them for book resources, so give it a simple stand-in.
if (typeof URL.createObjectURL !== "function") {
  let counter = 0;
  const store = new Map<string, Blob>();
  URL.createObjectURL = (blob: Blob) => {
    const url = `blob:oneshelf/${++counter}`;
    store.set(url, blob);
    return url;
  };
  URL.revokeObjectURL = (url: string) => { store.delete(url); };
}

// Desktop unless a test says otherwise, and no remembered preferences leaking between tests.
beforeEach(() => {
  setViewport("desktop");
  try {
    window.localStorage.clear();
  } catch {
    // Blocked storage is a valid state for the app, and for its tests.
  }
});

// jsdom has no IntersectionObserver or ResizeObserver; Embla carousel needs both.
if (typeof IntersectionObserver === "undefined") {
  globalThis.IntersectionObserver = class {
    readonly root: Element | null = null;
    readonly rootMargin = "";
    readonly thresholds: ReadonlyArray<number> = [];
    private cb: IntersectionObserverCallback;
    constructor(cb: IntersectionObserverCallback) { this.cb = cb; }
    observe(target: Element) {
      this.cb([{ isIntersecting: true, target } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
    }
    unobserve() {}
    disconnect() {}
    takeRecords(): IntersectionObserverEntry[] { return []; }
  } as unknown as typeof IntersectionObserver;
}
if (typeof ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    constructor(_cb: ResizeObserverCallback) {}
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

// jsdom has no top layer. Browser tests verify real focus trapping and inertness.
HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
