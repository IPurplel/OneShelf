import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

import { setViewport } from "./viewport";

// Desktop unless a test says otherwise, and no remembered preferences leaking between tests.
beforeEach(() => {
  setViewport("desktop");
  try {
    window.localStorage.clear();
  } catch {
    // Blocked storage is a valid state for the app, and for its tests.
  }
});
