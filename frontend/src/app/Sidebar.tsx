import { NavLink } from "react-router-dom";

import { Icon } from "@/components/Icon";
import { useI18n } from "@/i18n/i18n";
import { DESTINATIONS } from "./navigation";

/** The fixed forest-green sidebar with the logo at the top (Master §32.1). */
export function Sidebar() {
  const { t } = useI18n();
  return (
    <div className="sidebar">
      <div className="sidebar__brand">
        <span className="sidebar__leaf" aria-hidden="true">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
            <path d="M20 4c0 8-5 13-12 13 0-8 5-13 12-13zM8 17c0 2-1 3-1 3" strokeLinecap="round" />
          </svg>
        </span>
        <span className="sidebar__name display">{t("app.name")}</span>
      </div>
      <nav className="sidebar__nav" aria-label={t("nav.primary")}>
        <ul>
          {DESTINATIONS.map((destination) => (
            <li key={destination.path}>
              <NavLink to={destination.path} end={destination.path === "/"}
                       className={({ isActive }) => (isActive ? "sidebar__link is-active" : "sidebar__link")}>
                <Icon name={destination.icon} />
                <span>{t(destination.labelKey)}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="sidebar__footer" aria-hidden="true">
        <svg className="sidebar__botanical" viewBox="0 0 120 160" fill="none" stroke="currentColor" strokeWidth="1.2">
          <path d="M60 158V54M60 92c0-18 13-32 31-36-2 20-14 33-31 36zM60 92c0-18-13-32-31-36 2 20 14 33 31 36z" />
          <path d="M60 62c0-16 11-28 27-31-2 17-12 28-27 31zM60 62c0-16-11-28-27-31 2 17 12 28 27 31z" />
          <path d="M60 124c0-16 11-28 27-31-2 17-12 28-27 31zM60 124c0-16-11-28-27-31 2 17 12 28 27 31z" />
        </svg>
        <p className="sidebar__note">{t("app.sidebarNote")}</p>
        <span className="sidebar__rule" />
      </div>
    </div>
  );
}
