import { ApiError, api } from "@/api/client";
import { useState } from "react";
import { useResource } from "@/api/useApi";
import type { NotificationsResponse } from "@/api/types";
import { Drawer } from "@/components/Drawer";
import { useI18n } from "@/i18n/i18n";
import { useNotifications } from "@/app/notifications";

/**
 * Notifications (Master §30, §32.13) and Needs Attention (§32.2, §44).
 *
 * One inbox on warm paper; Needs Attention is the same data filtered to unresolved, actionable problems
 * rather than a second list. Marking things seen never touches reading state (INV-22).
 */
export function NotificationsDrawer({ attentionOnly = false, onClose }: {
  attentionOnly?: boolean;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const counts = useNotifications();
  const { data, error, reload } = useResource<NotificationsResponse>("/api/notifications",
    attentionOnly ? { attention: true } : undefined);
  const [problem, setProblem] = useState<string | null>(null);

  const items = data?.notifications ?? [];

  const act = async (call: Promise<unknown>) => {
    setProblem(null);
    try {
      await call;
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      reload();
      void counts.refresh();
    }
  };

  return (
    <Drawer title={attentionOnly ? t("notify.attention") : t("notify.title")} onClose={onClose}>
      {error !== null && <><p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button></>}
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {!attentionOnly && (
        <div className="drawer__filters">
          <button type="button" className="chip" onClick={() => void act(api.post("/api/notifications/mark-all-seen"))}>
            {t("notify.markAll")}
          </button>
          <button type="button" className="chip" onClick={() => void act(api.post("/api/notifications/clear-seen"))}>
            {t("notify.clearSeen")}
          </button>
        </div>
      )}

      {data !== null && items.length === 0 && (
        <p className="shelf__empty">{attentionOnly ? t("notify.emptyAttention") : t("notify.empty")}</p>
      )}

      <ul className="notes">
        {items.map((item) => (
          <li key={item.id} className="notes__row" data-seen={item.seen ? "true" : "false"}
              data-class={item.notification_class}>
            <span className="notes__title">{item.title}</span>
            {item.count > 1 && <span className="notes__count">{item.count}</span>}
            <span className="notes__summary">{item.summary}</span>
          </li>
        ))}
      </ul>
    </Drawer>
  );
}
