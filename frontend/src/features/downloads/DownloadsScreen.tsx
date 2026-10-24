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
import { readerLink } from "@/features/reader/links";
import type { StringKey } from "@/i18n/strings";

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

type DownloadJob = {
  id: string;
  reading_unit_id: string;
  state: string;
  bytes_done?: number | null;
  bytes_total?: number | null;
  error_category?: string | null;
  last_error?: string | null;
  work_id?: string | null;
  work_title?: string | null;
  track_id?: string | null;
  unit_title?: string | null;
  available?: boolean | null;
  available_format?: string | null;
  storage_root_name?: string | null;
};
type BatchDetail = Batch & { jobs: DownloadJob[]; jobs_total?: number; limit?: number };
const JOB_ERROR_KEYS: Record<string, StringKey> = {
  auth_failure: "downloads.error.auth", rate_limit: "downloads.error.rate",
  transport: "downloads.error.transport", storage_error: "downloads.error.storage",
  storage_full: "downloads.error.storage", storage_unavailable: "downloads.error.storage",
  blocked: "downloads.error.blocked", media_invalid: "downloads.error.media",
  parser_failure: "downloads.error.source", selector_missing: "downloads.error.source",
  not_found: "downloads.error.source", unexpected_response: "downloads.error.source",
  resource_missing: "downloads.error.source", source_unlinked: "downloads.error.source",
};

/** Downloads (Master §16, §32.11): warm paper panels, real states, no shelves and no analytics. */
export function DownloadsScreen() {
  const { t } = useI18n();
  const { data, error, loading, reload } = useResource<{ batches: Batch[] }>("/api/downloads");

  // §36: the queue moves on its own, so the screen follows the library rather than a guess or a refresh.
  useLive(["download.batch", "download.job"], reload);
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

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
              <button type="button" className="chip" aria-expanded={expanded === batch.batch_id}
                      aria-controls={expanded === batch.batch_id ? `batch-details-${batch.batch_id}` : undefined}
                      onClick={() => setExpanded(expanded === batch.batch_id ? null : batch.batch_id)}>
                {t("downloads.details")}
              </button>
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
            {expanded === batch.batch_id && <BatchDetails batch={batch} />}
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

/**
 * Detail requests exist only while their batch is open; live job events refresh an open panel, and so does a
 * Work's files being deleted, since that changes which finished units can still be opened.
 */
function BatchDetails({ batch }: { batch: Batch }) {
  const { t, language } = useI18n();
  const [offset, setOffset] = useState(0);
  const { data, error, loading, reload } = useResource<BatchDetail>(`/api/downloads/${batch.batch_id}`, offset ? { offset } : undefined);
  useLive(["download.batch", "download.job", "shelf.changed"], reload);
  const bytes = (value: number) => new Intl.NumberFormat(language, { style: "unit", unit: "byte", unitDisplay: "narrow" }).format(value);
  return <div className="batches__detail" id={`batch-details-${batch.batch_id}`}>
    {loading && data === null && <LoadingState />}
    {error !== null && <><p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
      <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button></>}
    {data?.jobs.length === 0 && <p className="cards__meta">{t("downloads.noJobs")}</p>}
    {data?.jobs.map((job, index) => {
      const state = job.state.toUpperCase();
      const known = ["QUEUED", "PREPARING", "DOWNLOADING", "VERIFYING", "PACKAGING", "COMMITTING", "COMPLETED",
        "PAUSED", "WAITING_FOR_SESSION", "WAITING_FOR_RATE_LIMIT", "RETRY_WAIT", "FAILED", "CANCELED", "RECOVERING"];
      const label = job.unit_title || t("downloads.unitFallback", { number: offset + index + 1 });
      // Only the API's word that the file is there now makes a unit openable; an older API says nothing (UI-003).
      const openable = state === "COMPLETED" && job.available === true;
      return <div key={job.id} className="batches__job">
        <span className="batches__jobTitle" dir="auto">{label}</span>
        {job.work_title && <span className="cards__meta" dir="auto">{job.work_title}</span>}
        <span className="cards__meta">{known.includes(state)
          ? t(`downloads.job.${state}` as StringKey) : t("downloads.job.unknown")}</span>
        {job.bytes_done != null && job.bytes_done > 0 && <span className="cards__meta">
          {job.bytes_total && job.bytes_total > 0 ? t("downloads.bytesProgress", { done: bytes(job.bytes_done), total: bytes(job.bytes_total) })
            : t("downloads.bytesDone", { done: bytes(job.bytes_done) })}
        </span>}
        {job.bytes_total != null && job.bytes_total > 0 && state !== "COMPLETED" &&
          <progress className="batches__jobProgress" value={Math.min(job.bytes_total, Math.max(0, job.bytes_done ?? 0))}
            max={job.bytes_total} aria-label={t("downloads.unitProgress", { title: label })} />}
        {state === "FAILED" && <span className="batches__error">{t(JOB_ERROR_KEYS[job.error_category ?? ""] ?? "downloads.error.other")}</span>}
        {state === "COMPLETED" && job.available === false && <span className="batches__error">{t("downloads.unavailable")}</span>}
        {openable && job.storage_root_name && <span className="cards__meta">{t("downloads.storedIn", { location: job.storage_root_name })}</span>}
        {openable && <span className="batches__actions">
          <Link className="chip" to={readerLink(job.reading_unit_id, job.work_id ?? "", job.track_id, job.available_format)}
            aria-label={t("downloads.openUnit", { title: label })}>{t("downloads.open")}</Link>
          <a className="chip" href={`/api/downloads/jobs/${job.id}/file`} download
            aria-label={t("downloads.saveFile", { title: label })}>{t("downloads.save")}</a>
        </span>}
      </div>;
    })}
    {(offset > 0 || (data?.jobs_total ?? 0) > (data?.limit ?? 500)) && <div className="batches__actions">
      <button type="button" className="chip" disabled={loading || offset === 0}
        onClick={() => setOffset(Math.max(0, offset - (data?.limit ?? 500)))}>{t("downloads.previousPage")}</button>
      <button type="button" className="chip" disabled={loading || offset + (data?.limit ?? 500) >= (data?.jobs_total ?? 0)}
        onClick={() => setOffset(offset + (data?.limit ?? 500))}>{t("downloads.nextPage")}</button>
    </div>}
    {batch.skipped > 0 && <p className="cards__meta">{t("downloads.skippedExplanation", { count: batch.skipped })}</p>}
  </div>;
}
