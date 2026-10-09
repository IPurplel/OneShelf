import { NavLink, useLocation } from "react-router-dom";

import { Icon } from "@/components/Icon";
import { useI18n } from "@/i18n/i18n";
import { DESTINATIONS } from "./navigation";

/** Mobile is not a shrunken desktop (Master §32.21): four destinations plus More. */
export function BottomNav({ onOpenMore, moreOpen }: { onOpenMore: () => void; moreOpen: boolean }) {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const moreActive = moreOpen || DESTINATIONS.some((destination) =>
    !destination.mobile && (pathname === destination.path || pathname.startsWith(`${destination.path}/`)));
  return (
    <nav className="bottomnav" aria-label={t("nav.primary")}>
      {DESTINATIONS.filter((d) => d.mobile).map((destination) => (
        <NavLink key={destination.path} to={destination.path} end={destination.path === "/"}
                 className={({ isActive }) => (isActive ? "bottomnav__link is-active" : "bottomnav__link")}>
          <Icon name={destination.icon} />
          <span>{t(destination.labelKey)}</span>
        </NavLink>
      ))}
      <button type="button" className={moreActive ? "bottomnav__link is-active" : "bottomnav__link"}
              aria-expanded={moreOpen} aria-haspopup="dialog" onClick={onOpenMore}>
        <Icon name="more" />
        <span>{t("nav.more")}</span>
      </button>
    </nav>
  );
}
