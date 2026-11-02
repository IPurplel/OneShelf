import { api } from "@/api/client";
import { useState } from "react";
import { useResource } from "@/api/useApi";
import { Link } from "react-router-dom";
import type { Notification, NotificationsResponse } from "@/api/types";
import { workLink } from "@/features/reader/links";
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
  const { t, errorText } = useI18n();
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
      setProblem(errorText(error));
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
      {!attentionOnly && data !== null && items.length > 0 && (
        <div className="drawer__filters">
          {items.some(item => !item.seen) && <button type="button" className="chip" onClick={() => void act(api.post("/api/notifications/mark-all-seen"))}>
            {t("notify.markAll")}
          </button>}
          {items.some(item => item.seen) && <button type="button" className="chip" onClick={() => void act(api.post("/api/notifications/clear-seen"))}>
            {t("notify.clearSeen")}
          </button>}
        </div>
      )}

      {data !== null && items.length === 0 && (
        <div className="empty"><p className="empty__body">{attentionOnly ? t("notify.emptyAttention") : t("notify.empty")}</p></div>
      )}

      <ul className="notes">
        {items.map((item) => (
          <li key={item.id} className="notes__row" data-seen={item.seen ? "true" : "false"}
              data-class={item.notification_class}>
            <span className="notes__title" dir="auto">{item.title}</span>
            {item.count > 1 && <span className="notes__count">{item.count}</span>}
            <span className="notes__summary">{item.summary}</span>
            <NoteActions item={item} onClose={onClose} onAct={act} />
          </li>
        ))}
      </ul>
    </Drawer>
  );
}

/**
 * Each problem offers the one step that answers it (§44): open the work, try the download again, reconnect
 * the source, or look at storage. The notification says which; nothing here guesses.
 */
function NoteActions({ item, onClose, onAct }: {
  item: Notification; onClose: () => void; onAct: (call: Promise<unknown>) => Promise<void>;
}) {
  const { t } = useI18n();
  const payload = item.payload as { work_id?: string; track_id?: string; unit_id?: string };
  const kind = item.dedupe_key.split(":")[0];
  const links: { to: string; label: string }[] = [];
  if (payload.work_id) links.push({ to: workLink(payload.work_id, payload.track_id), label: t("work.open") });
  if (kind === "source-auth" || kind === "source-bootstrap" || kind === "plugin-update") {
    links.push({ to: "/sources", label: t("nav.sources") });
  }
  if (kind === "storage-low" || kind === "storage-unavailable") {
    links.push({ to: "/settings/storage", label: t("downloads.storageSettings") });
  }
  const retry = kind === "download-failed" && payload.unit_id && item.state === "active";
  if (links.length === 0 && !retry) return null;
  return (
    <span className="notes__actions">
      {retry && (
        <button type="button" className="chip"
                onClick={() => void onAct(api.post("/api/downloads", { unit_ids: [payload.unit_id] }))}>
          {t("downloads.retry")}
        </button>
      )}
      {links.map((link) => (
        <Link key={link.to} className="chip" to={link.to} onClick={onClose}>{link.label}</Link>
      ))}
    </span>
  );
}
