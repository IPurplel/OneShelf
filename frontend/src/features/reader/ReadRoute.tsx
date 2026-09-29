import { Link, useParams, useSearchParams } from "react-router-dom";

import { useResource } from "@/api/useApi";
import type { WorkDetails } from "@/api/types";
import { useI18n } from "@/i18n/i18n";
import { BookReader } from "./BookReader";
import { ReaderScreen } from "./ReaderScreen";
import { workLink } from "./links";

type UnitContext = { work_id: string; track_id: string; formats: string[] };

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
  const { data, error, loading, reload } = useResource<UnitContext>(`/api/reader/units/${unitId}/context`);
  if (error !== null) return <Unavailable message={error} back={workLink(workId ?? "", trackId)} retry={reload} />;
  if (loading || data === null) return <p className="screen__subtitle">{t("state.loading")}</p>;
  return <OpenUnit unitId={unitId} workId={workId ?? data.work_id} trackId={trackId ?? data.track_id} formats={data.formats} />;
}
function OpenUnit({ unitId, workId, trackId, formats }: { unitId: string; workId: string; trackId: string; formats: string[] }) {
  const { t } = useI18n();
  const { data, error, loading, reload } = useResource<WorkDetails>(`/api/works/${workId}`, { track_id: trackId });
  if (error !== null) return <Unavailable message={error} back={workLink(workId, trackId)} retry={reload} />;
  if (loading || data === null) return <p className="screen__subtitle">{t("state.loading")}</p>;
  if (!data.units.some(unit => unit.id === unitId)) {
    return <Unavailable message={t("reader.unitUnavailable")} back={workLink(workId, trackId)} retry={reload} />;
  }
  if (formats.includes("epub")) return <BookReader unitId={unitId} format="epub" workId={workId} trackId={trackId} />;
  if (formats.includes("pdf")) return <BookReader unitId={unitId} format="pdf" workId={workId} trackId={trackId} />;
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
