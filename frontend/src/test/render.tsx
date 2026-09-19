import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { App } from "@/app/App";
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
