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
