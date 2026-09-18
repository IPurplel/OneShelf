import { useI18n } from "@/i18n/i18n";
import { Icon } from "@/components/Icon";
import { useNotifications } from "./notifications";

/**
 * Header controls only (Master §32.2): notifications, Needs Attention when something is unresolved,
 * and the language switch. There is no profile or avatar — OneShelf has no account.
 */
export function Header({ onOpenNotifications, onOpenAttention }: {
  onOpenNotifications: () => void;
  onOpenAttention: () => void;
}) {
  const { t, language, toggleLanguage } = useI18n();
  const { unseen, attention } = useNotifications();

  return (
    <header className="header" role="banner">
      <div className="header__spacer" />
      <p className="header__promise">
        <span className="header__leaf" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
            <path d="M20 4c0 8-5 13-12 13 0-8 5-13 12-13zM8 17c0 2-1 3-1 3" strokeLinecap="round" />
          </svg>
        </span>
        {t("app.promise")}
      </p>
      <div className="header__controls">
        <button type="button" className="header__button" onClick={toggleLanguage}>
          {/* The label is written in the language it switches to, so it is marked as such. */}
          <span lang={language === "en" ? "ar" : "en"}>{t("header.language")}</span>
        </button>
        {attention > 0 && (
          <button type="button" className="header__button header__button--attention" onClick={onOpenAttention}>
            <Icon name="attention" />
            <span className="header__count">{attention}</span>
            <span className="visually-hidden">{t("header.attention")}</span>
            <span aria-hidden="true" className="visually-hidden">{t("header.attention")}</span>
          </button>
        )}
        <button type="button" className="header__button" onClick={onOpenNotifications}
                aria-label={unseen > 0 ? `${t("header.notifications")} (${unseen})` : t("header.notifications")}>
          <Icon name="bell" />
          {unseen > 0 && <span className="header__dot" aria-hidden="true" />}
        </button>
      </div>
    </header>
  );
}
