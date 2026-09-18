import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

import { setViewport } from "./viewport";

// Desktop unless a test says otherwise.
beforeEach(() => setViewport("desktop"));
