import { useState } from "react";

import { ApiError, api } from "@/api/client";
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
  const { data, error, reload } = useResource<NotificationSettings>("/api/notifications/settings");
  const [problem, setProblem] = useState<string | null>(null);

  if (data === null) return <section className="paper">{error !== null ? <>
    <p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
    <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button>
  </> : <p>{t("state.loading")}</p>}</section>;

  return (
    <section className="paper">
      <h2 className="display">{t("settings.notifications")}</h2>
      <p className="firstrun__lede">{t("settings.notifications.help")}</p>
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}

      <label className="panel__choice">
        <input type="checkbox" checked={data.source_recovered}
               onChange={() => {
                 setProblem(null);
                 void api.post("/api/notifications/settings", { source_recovered: !data.source_recovered })
                   .then(reload).catch(error => setProblem(error instanceof ApiError ? error.message : t("state.offline")));
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
