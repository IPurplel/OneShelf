import { useCallback, useEffect, useState } from "react";
import { Link, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { useI18n } from "@/i18n/i18n";
import { MOBILE_QUERY, useMediaQuery } from "./useMediaQuery";
import { BottomNav } from "./BottomNav";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { NotificationsDrawer } from "@/features/notifications/NotificationsDrawer";
import { Drawer } from "@/components/Drawer";
import { Icon } from "@/components/Icon";
import { DESTINATIONS } from "./navigation";
import { routes } from "./routes";

function Layout() {
  const { t } = useI18n();
  const [panel, setPanel] = useState<null | "notifications" | "attention" | "more">(null);
  const closePanel = useCallback(() => setPanel(null), []);
  const location = useLocation();
  useEffect(closePanel, [location, closePanel]);
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
      {panel === "more" && (
        <Drawer title={t("nav.more")} onClose={closePanel}>
          <nav className="more__nav" aria-label={t("nav.more")}>
            {DESTINATIONS.filter(destination => !destination.mobile).map(destination => (
              <Link key={destination.path} className="button" to={destination.path} onClick={closePanel}>
                <Icon name={destination.icon} />{t(destination.labelKey)}
              </Link>
            ))}
            <button type="button" className="button" onClick={() => setPanel("notifications")}>
              <Icon name="bell" />{t("notify.title")}
            </button>
          </nav>
        </Drawer>
      )}
      {(panel === "notifications" || panel === "attention") && (
        <NotificationsDrawer attentionOnly={panel === "attention"} onClose={closePanel} />
      )}
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
