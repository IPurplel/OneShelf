import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";

import { App } from "@/app/App";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { LiveProvider } from "@/app/live";
import { NotificationProvider } from "@/app/notifications";
import { ThemeProvider } from "@/app/theme";
import { I18nProvider } from "@/i18n/i18n";
// Self-hosted so a fresh install looks right offline and reaches no third party (Master §2.1, §49).
import "@fontsource/noto-serif/latin-400.css";
import "@fontsource/noto-serif/latin-600.css";
import "@fontsource/noto-serif/latin-400-italic.css";
import "@fontsource/noto-naskh-arabic/arabic-400.css";
import "@fontsource/noto-naskh-arabic/arabic-600.css";

import "@/styles/tailwind.css";
import "@/styles/base.css";
import "@/styles/shell.css";
import "@/styles/library.css";
import "@/styles/reader.css";

const container = document.getElementById("root");
if (container === null) throw new Error("missing #root");

createRoot(container).render(
  <StrictMode>
    <ErrorBoundary>
    <ThemeProvider>
      <I18nProvider>
        <LiveProvider>
          <NotificationProvider>
            <BrowserRouter>
              <App />
              <Toaster
                position="bottom-right"
                toastOptions={{
                  style: {
                    background: "var(--paper)",
                    border: "1px solid var(--surface-border)",
                    color: "var(--ink-900)",
                    fontFamily: "var(--font-ui)",
                  },
                }}
              />
            </BrowserRouter>
          </NotificationProvider>
        </LiveProvider>
      </I18nProvider>
    </ThemeProvider>
    </ErrorBoundary>
  </StrictMode>,
);
