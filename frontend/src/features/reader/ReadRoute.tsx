import { useParams, useSearchParams } from "react-router-dom";

import { useResource } from "@/api/useApi";
import type { WorkDetails } from "@/api/types";
import { useI18n } from "@/i18n/i18n";
import { BookReader } from "./BookReader";
import { ReaderScreen } from "./ReaderScreen";

/**
 * One reading route, two reader families (Master §26): sequential art opens the page reader, books open
 * the isolated document reader. The unit's own formats decide, not a guess from the content type.
 */
export function ReadRoute() {
  const params = useParams();
  const [search] = useSearchParams();
  const { t } = useI18n();
  const unitId = params.unitId ?? "";
  const workId = search.get("work") ?? "";
  const { data } = useResource<WorkDetails>(`/api/works/${workId}`);

  if (workId === "") return <ReaderScreen unitId={unitId} workId={workId} />;
  if (data === null) return <p className="screen__subtitle">{t("state.loading")}</p>;

  const unit = data.units.find((candidate) => candidate.id === unitId);
  const formats = unit?.formats ?? [];
  if (formats.includes("epub")) return <BookReader unitId={unitId} format="epub" workId={workId} />;
  if (formats.includes("pdf")) return <BookReader unitId={unitId} format="pdf" workId={workId} />;
  return <ReaderScreen unitId={unitId} workId={workId} />;
}
