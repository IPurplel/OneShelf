import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";

type NotificationSettings = { source_recovered: boolean };

/**
 * Notification settings (Master §30, §32.14).
 *
 * OneShelf notifies in the app and nowhere else (§49): no browser notifications, no push, nothing
 * leaves the machine. The one thing worth choosing is whether a source coming back is worth saying —
 * §30.10 says it is optional and silent by default.
 */
export function NotificationSettingsPanel() {
  const { t } = useI18n();
  const { data, reload } = useResource<NotificationSettings>("/api/notifications/settings");

  if (data === null) return <section className="paper"><p>{t("state.loading")}</p></section>;

  return (
    <section className="paper">
      <h2 className="display">{t("settings.notifications")}</h2>
      <p className="firstrun__lede">{t("settings.notifications.help")}</p>

      <label className="panel__choice">
        <input type="checkbox" checked={data.source_recovered}
               onChange={() => {
                 void api.post("/api/notifications/settings", { source_recovered: !data.source_recovered })
                   .finally(reload);
               }} />
        <span>
          <span className="panel__choiceTitle">{t("settings.notifications.recovered")}</span>
          <span className="panel__choiceHelp">{t("settings.notifications.recoveredHelp")}</span>
        </span>
      </label>

      <p className="cards__meta">{t("settings.notifications.history")}</p>
    </section>
  );
}
