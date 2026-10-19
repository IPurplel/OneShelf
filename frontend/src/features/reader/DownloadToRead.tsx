import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/client";
import { useLive } from "@/app/live";
import { apiErrorText } from "@/i18n/apiErrors";
import { useI18n } from "@/i18n/i18n";
import { workLink } from "./links";

export type DownloadState = { state: string | null; error: string | null };

const ACTIVE = new Set(["QUEUED", "PREPARING", "DOWNLOADING", "VERIFYING", "PACKAGING", "COMMITTING", "RECOVERING",
                        "RETRY_WAIT", "WAITING_FOR_RATE_LIMIT", "WAITING_FOR_SESSION", "PAUSED"]);
const LIVE = ["download.job", "download.batch"] as const;

/**
 * A book whose source offers only its file (no `reader` recipe) is read once it is downloaded — never by
 * asking the source for pages it does not have. Nothing downloads until the reader asks (Master §19);
 * when the file arrives the route reloads its context and opens the Book Reader.
 */
export function DownloadToRead({ unitId, workId, trackId, download, onChange }: {
  unitId: string; workId: string; trackId: string; download: DownloadState; onChange: () => void;
}) {
  const { t, language } = useI18n();
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  useLive(LIVE, onChange);

  const start = async () => {
    setStarting(true);
    setProblem(null);
    try {
      await api.post("/api/downloads", { unit_ids: [unitId] });
      onChange();
    } catch (error) {
      setProblem(apiErrorText(error, language, t));
    } finally {
      setStarting(false);
    }
  };

  const active = download.state !== null && ACTIVE.has(download.state);
  const failed = download.state === "FAILED";
  return (
    <section className="screen">
      <h1 className="screen__title">{t("reader.download.title")}</h1>
      <p className="screen__subtitle">{t("reader.download.body")}</p>
      {failed && <p className="notice notice--problem" role="alert">{t("reader.download.failed")}</p>}
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {active
        ? <p className="notice" role="status">{t("reader.download.inProgress")}</p>
        : <button className="button button--primary" type="button" disabled={starting} onClick={() => void start()}>
            {t(failed ? "reader.download.retry" : "reader.download.action")}
          </button>}
      <Link className="button" to={workLink(workId, trackId)}>{t("reader.backToWork")}</Link>
    </section>
  );
}
