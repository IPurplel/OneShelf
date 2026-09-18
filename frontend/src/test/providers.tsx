import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";

import { NotificationProvider } from "@/app/notifications";
import { I18nProvider } from "@/i18n/i18n";

export function TestProviders({ children, route = "/", notifications = { unseen: 0, attention: 0 } }: {
  children: ReactNode;
  route?: string;
  notifications?: { unseen: number; attention: number };
}) {
  return (
    <I18nProvider language="en">
      <NotificationProvider initial={notifications}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </NotificationProvider>
    </I18nProvider>
  );
}
