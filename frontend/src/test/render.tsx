import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { vi } from "vitest";

import { App } from "@/app/App";
import { LiveProvider } from "@/app/live";
import { TestProviders } from "@/test/providers";

export type TestOptions = {
  route?: string;
  notifications?: { unseen: number; attention: number };
  language?: "en" | "ar";
};

export function renderApp(options: TestOptions = {}) {
  return render(<TestProviders {...options}><App /></TestProviders>);
}

export function renderWithProviders(ui: ReactElement, options: TestOptions = {}) {
  return render(<TestProviders {...options}>{ui}</TestProviders>);
}

type Handler = (event: { data: string }) => void;

/** Renders inside the live channel, with a fake stream the test can push events through (§36). */
export function renderLive(ui: ReactElement, options: TestOptions = {}) {
  const listeners = new Map<string, Handler[]>();
  class TestEventSource {
    constructor(readonly url: string) { queueMicrotask(() => this.fire("hello", {})); }
    addEventListener(name: string, handler: Handler) {
      listeners.set(name, [...(listeners.get(name) ?? []), handler]);
    }
    close() {}
    onerror: (() => void) | null = null;
    fire(name: string, payload: unknown) {
      for (const handler of listeners.get(name) ?? []) handler({ data: JSON.stringify(payload) });
    }
  }
  vi.stubGlobal("EventSource", TestEventSource);
  const rendered = render(
    <TestProviders {...options}><LiveProvider>{ui}</LiveProvider></TestProviders>);
  return {
    ...rendered,
    emit: (name: string, payload: unknown) => {
      for (const handler of listeners.get(name) ?? []) handler({ data: JSON.stringify(payload) });
    },
  };
}
