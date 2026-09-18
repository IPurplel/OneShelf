import { useState } from "react";
import { Outlet, Route, Routes } from "react-router-dom";

import { useI18n } from "@/i18n/i18n";
import { MOBILE_QUERY, useMediaQuery } from "./useMediaQuery";
import { BottomNav } from "./BottomNav";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { routes } from "./routes";

function Layout() {
  const { t } = useI18n();
  const [panel, setPanel] = useState<null | "notifications" | "attention" | "more">(null);
  const mobile = useMediaQuery(MOBILE_QUERY);

  return (
    <div className="layout">
      <a className="skip-link" href="#main">{t("skip.content")}</a>
      {!mobile && (
        <aside className="layout__sidebar">
          <Sidebar />
        </aside>
      )}
      <div className="layout__body">
        <Header onOpenNotifications={() => setPanel("notifications")} onOpenAttention={() => setPanel("attention")} />
        <main id="main" className="layout__main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
      {mobile && <BottomNav onOpenMore={() => setPanel("more")} />}
      {panel !== null && <div className="visually-hidden" data-panel={panel} />}
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        {routes.map((route) => (
          <Route key={route.path} path={route.path} element={route.element} />
        ))}
      </Route>
    </Routes>
  );
}
