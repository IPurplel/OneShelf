import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "@/app/App";
import { NotificationProvider } from "@/app/notifications";
import { I18nProvider } from "@/i18n/i18n";
import "@/styles/base.css";
import "@/styles/shell.css";

const container = document.getElementById("root");
if (container === null) throw new Error("missing #root");

createRoot(container).render(
  <StrictMode>
    <I18nProvider>
      <NotificationProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </NotificationProvider>
    </I18nProvider>
  </StrictMode>,
);
