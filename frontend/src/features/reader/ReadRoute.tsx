import { Link, useParams, useSearchParams } from "react-router-dom";

import { useResource } from "@/api/useApi";
import type { WorkDetails } from "@/api/types";
import { useI18n } from "@/i18n/i18n";
import { BookReader } from "./BookReader";
import { DownloadToRead, type DownloadState } from "./DownloadToRead";
import { ReaderScreen } from "./ReaderScreen";
import { workLink } from "./links";

type UnitContext = { work_id: string; track_id: string; formats: string[]; kind?: "images" | "text" | "download";
                     download?: DownloadState };

/** Resolve old unit-only links as well as explicit work/track links before selecting a reader. */
export function ReadRoute() {
  const { unitId = "" } = useParams();
  const [search] = useSearchParams();
  const workId = search.get("work");
  const trackId = search.get("track");
  return <ResolveUnit key={`${unitId}:${workId}:${trackId}`} unitId={unitId} workId={workId} trackId={trackId} />;
}
function ResolveUnit({ unitId, workId, trackId }: { unitId: string; workId: string | null; trackId: string | null }) {
  const { t } = useI18n();
  const { data, error, reload } = useResource<UnitContext>(`/api/reader/units/${unitId}/context`);
  if (error !== null) return <Unavailable message={error} back={workLink(workId ?? "", trackId)} retry={reload} />;
  // A reload keeps what is shown (a download finishing, say) instead of blanking the reader.
  if (data === null) return <p className="screen__subtitle">{t("state.loading")}</p>;
  const download = data.kind === "download" ? data.download ?? { state: null, error: null } : null;
  return <OpenUnit unitId={unitId} workId={workId ?? data.work_id} trackId={trackId ?? data.track_id} formats={data.formats}
                   text={data.kind === "text"} download={download} onChange={reload} />;
}
function OpenUnit({ unitId, workId, trackId, formats, text, download, onChange }: {
  unitId: string; workId: string; trackId: string; formats: string[]; text: boolean;
  download: DownloadState | null; onChange: () => void;
}) {
  const { t } = useI18n();
  const [search] = useSearchParams();
  const requestedFormat = search.get("format");
  const { data, error, loading, reload } = useResource<WorkDetails>(`/api/works/${workId}`, { track_id: trackId });
  if (error !== null) return <Unavailable message={error} back={workLink(workId, trackId)} retry={reload} />;
  if (loading || data === null) return <p className="screen__subtitle">{t("state.loading")}</p>;
  if (!data.units.some(unit => unit.id === unitId)) {
    return <Unavailable message={t("reader.unitUnavailable")} back={workLink(workId, trackId)} retry={reload} />;
  }
  if (formats.length === 0 && data.tracks?.some(track => track.id === trackId && track.kind === "source"
      && track.listing_id === null && track.availability === "unavailable")) {
    return <section className="screen">
      <p className="notice notice--problem" role="alert">{t("work.track.archived")}</p>
      <Link className="button" to={workLink(workId, trackId)}>{t("reader.backToWork")}</Link>
    </section>;
  }
  if (requestedFormat && formats.includes(requestedFormat)) {
    if (requestedFormat === "epub" || requestedFormat === "pdf" || requestedFormat === "text")
      return <BookReader unitId={unitId} format={requestedFormat} workId={workId} trackId={trackId} />;
    if (requestedFormat === "cbz") return <ReaderScreen unitId={unitId} workId={workId} trackId={trackId} />;
  }
  if (formats.includes("epub")) return <BookReader unitId={unitId} format="epub" workId={workId} trackId={trackId} />;
  if (formats.includes("pdf")) return <BookReader unitId={unitId} format="pdf" workId={workId} trackId={trackId} />;
  // A text unit is read in the Book Reader, downloaded or not: it has no pages to show (plugin API 1.2).
  if (text || formats.includes("text")) return <BookReader unitId={unitId} format="text" workId={workId} trackId={trackId} />;
  // A download-only source has no pages to show: the book is read from its file (plugin without `reader`).
  if (download !== null) {
    return <DownloadToRead unitId={unitId} workId={workId} trackId={trackId} download={download} onChange={onChange} />;
  }
  return <ReaderScreen unitId={unitId} workId={workId} trackId={trackId} />;
}
function Unavailable({ message, back, retry }: { message: string; back: string; retry: () => void }) {
  const { t } = useI18n();
  return <section className="screen">
    <p className="notice notice--problem" role="alert">{message === "offline" ? t("state.offline") : message}</p>
    <button className="button" type="button" onClick={retry}>{t("reader.retry")}</button>
    <Link className="button" to={back}>{t("reader.backToWork")}</Link>
  </section>;
}
