import { useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "motion/react";

import { ApiError, api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import { useLive } from "@/app/live";
import { TRANSITION_EASE, useReducedMotion } from "@/lib/motion";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { LoadingState } from "@/components/LoadingState";

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
  const { data, error, loading, reload } = useResource<{ batches: Batch[] }>("/api/downloads");

  // §36: the queue moves on its own, so the screen follows the library rather than a guess or a refresh.
  useLive(["download.batch", "download.job"], reload);
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const act = async (call: Promise<unknown>) => {
    setProblem(null);
    try {
      await call;
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      reload();
    }
  };

  const batches = data?.batches ?? [];
  const reduced = useReducedMotion();

  return (
    <section className="screen">
      <div className="screen__head">
        <h1 className="screen__title">{t("downloads.title")}</h1>
        {batches.length > 0 && (
          <button type="button" className="button" disabled={loading} onClick={() => setConfirming(true)}>{t("downloads.clear")}</button>
        )}
      </div>

      {error !== null && <><p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button></>}
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {loading && <LoadingState />}

      {data !== null && !loading && batches.length === 0 && <div className="empty">
        <p className="empty__body">{t("downloads.empty")}</p>
        <Link className="button button--primary" to="/shelf">{t("nav.shelf")}</Link>
      </div>}

      <ul className="batches">
        {batches.map((batch, index) => {
          const processed = batch.completed + batch.failed + batch.canceled + batch.skipped;
          const total = processed + batch.pending;
          return (
          <motion.li key={batch.batch_id} className="batches__row"
            initial={reduced ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...TRANSITION_EASE, delay: Math.min(index * 0.05, 0.2) }}
          >
            <span className={`batches__state batches__state--${batch.state}`}>{t(`downloads.state.${batch.state}`)}</span>
            <span className="batches__counts">
              <span>{t("downloads.done", { count: batch.completed })}</span>
              {batch.pending > 0 && <span>{t("downloads.waiting", { count: batch.pending })}</span>}
              {batch.failed > 0 && <span>{t("downloads.failed", { count: batch.failed })}</span>}
              {batch.skipped > 0 && <span>{t("downloads.skipped", { count: batch.skipped })}</span>}
              {batch.canceled > 0 && <span>{t("downloads.canceled", { count: batch.canceled })}</span>}
            </span>
            <progress className="batches__progress" value={processed} max={Math.max(1, total)}
                      aria-label={t("downloads.progress", { done: processed, total })} />
            <span className="batches__actions">
              {batch.state === "active" && (
                <button type="button" className="chip" disabled={loading} aria-label={`${t("downloads.pause")} · ${batch.batch_id}`}
                        onClick={() => void act(api.post(`/api/downloads/${batch.batch_id}/pause`))}>
                  {t("downloads.pause")}
                </button>
              )}
              {batch.state === "paused" && (
                <button type="button" className="chip" disabled={loading} aria-label={`${t("downloads.resume")} · ${batch.batch_id}`}
                        onClick={() => void act(api.post(`/api/downloads/${batch.batch_id}/resume`))}>
                  {t("downloads.resume")}
                </button>
              )}
              {batch.failed > 0 && (
                <button type="button" className="chip" disabled={loading} aria-label={`${t("downloads.retry")} · ${batch.batch_id}`}
                        onClick={() => void act(api.post(`/api/downloads/${batch.batch_id}/retry-failed`))}>
                  {t("downloads.retry")}
                </button>
              )}
              {(batch.state === "active" || batch.state === "paused") && (
                <button type="button" className="chip" disabled={loading} aria-label={`${t("downloads.cancel")} · ${batch.batch_id}`}
                        onClick={() => void act(api.post(`/api/downloads/${batch.batch_id}/cancel`))}>
                  {t("downloads.cancel")}
                </button>
              )}
            </span>
          </motion.li>
          );
        })}
      </ul>

      {confirming && (
        <ConfirmDialog title={t("downloads.clear")} body={t("downloads.clearExplain")}
                       confirmLabel={t("downloads.clear")} onCancel={() => setConfirming(false)}
                       onConfirm={() => { setConfirming(false); void act(api.delete("/api/downloads/history")); }} />
      )}
    </section>
  );
}
