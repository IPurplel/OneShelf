import { useState } from "react";

import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import { useLive } from "@/app/live";
import { ConfirmDialog } from "@/components/ConfirmDialog";

type Batch = {
  batch_id: string;
  state: "active" | "paused" | "completed" | "completed_with_issues" | "failed";
  completed: number;
  failed: number;
  pending: number;
  canceled: number;
  skipped: number;
  counts: Record<string, number>;
};

/** Downloads (Master §16, §32.11): warm paper panels, real states, no shelves and no analytics. */
export function DownloadsScreen() {
  const { t } = useI18n();
  const { data, reload } = useResource<{ batches: Batch[] }>("/api/downloads");

  // §36: the queue moves on its own, so the screen follows the library rather than a guess or a refresh.
  useLive(["download.batch", "download.job"], reload);
  const [confirming, setConfirming] = useState(false);

  const act = async (call: Promise<unknown>) => {
    try {
      await call;
    } finally {
      reload();
    }
  };

  const batches = data?.batches ?? [];

  return (
    <section className="screen">
      <div className="screen__head">
        <h1 className="screen__title">{t("downloads.title")}</h1>
        {batches.length > 0 && (
          <button type="button" className="button" onClick={() => setConfirming(true)}>{t("downloads.clear")}</button>
        )}
      </div>

      {data !== null && batches.length === 0 && <p className="shelf__empty">{t("downloads.empty")}</p>}

      <ul className="batches">
        {batches.map((batch) => (
          <li key={batch.batch_id} className="batches__row">
            <span className={`batches__state batches__state--${batch.state}`}>{batch.state.replace(/_/g, " ")}</span>
            <span className="batches__counts">
              <span>{t("downloads.done", { count: batch.completed })}</span>
              {batch.pending > 0 && <span>{t("downloads.waiting", { count: batch.pending })}</span>}
              {batch.failed > 0 && <span>{t("downloads.failed", { count: batch.failed })}</span>}
              {batch.skipped > 0 && <span>{t("downloads.skipped", { count: batch.skipped })}</span>}
            </span>
            <span className="batches__actions">
              {batch.state === "active" && (
                <button type="button" className="chip"
                        onClick={() => void act(api.post(`/api/downloads/${batch.batch_id}/pause`))}>
                  {t("downloads.pause")}
                </button>
              )}
              {batch.state === "paused" && (
                <button type="button" className="chip"
                        onClick={() => void act(api.post(`/api/downloads/${batch.batch_id}/resume`))}>
                  {t("downloads.resume")}
                </button>
              )}
              {batch.failed > 0 && (
                <button type="button" className="chip"
                        onClick={() => void act(api.post(`/api/downloads/${batch.batch_id}/retry-failed`))}>
                  {t("downloads.retry")}
                </button>
              )}
              {(batch.state === "active" || batch.state === "paused") && (
                <button type="button" className="chip"
                        onClick={() => void act(api.post(`/api/downloads/${batch.batch_id}/cancel`))}>
                  {t("downloads.cancel")}
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>

      {confirming && (
        <ConfirmDialog title={t("downloads.clear")} body={t("downloads.clearExplain")}
                       confirmLabel={t("downloads.clear")} onCancel={() => setConfirming(false)}
                       onConfirm={() => { setConfirming(false); void act(api.delete("/api/downloads/history")); }} />
      )}
    </section>
  );
}
