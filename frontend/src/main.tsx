import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "@/app/App";
import { LiveProvider } from "@/app/live";
import { NotificationProvider } from "@/app/notifications";
import { I18nProvider } from "@/i18n/i18n";
// Self-hosted so a fresh install looks right offline and reaches no third party (Master §2.1, §49).
import "@fontsource/noto-serif/latin-400.css";
import "@fontsource/noto-serif/latin-600.css";
import "@fontsource/noto-serif/latin-400-italic.css";
import "@fontsource/noto-naskh-arabic/arabic-400.css";
import "@fontsource/noto-naskh-arabic/arabic-600.css";

import "@/styles/base.css";
import "@/styles/shell.css";
import "@/styles/library.css";
import "@/styles/reader.css";

const container = document.getElementById("root");
if (container === null) throw new Error("missing #root");

createRoot(container).render(
  <StrictMode>
    <I18nProvider>
      <LiveProvider>
        <NotificationProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </NotificationProvider>
      </LiveProvider>
    </I18nProvider>
  </StrictMode>,
);
