import { Link } from "react-router-dom";

import { Drawer } from "@/components/Drawer";
import { useI18n } from "@/i18n/i18n";
import { languageName } from "@/i18n/language";

export type Alternative = {
  track_id: string;
  source_id: string;
  language: string;
  kind: "source" | "local";
  availability: string;
  unit_id: string | null;
  unit_title: string | null;
  confident: boolean;
  reason: "no_match" | "ambiguous" | null;
};

export type Alternatives = {
  unit_id: string;
  track_id: string;
  source_id: string;
  language: string;
  alternatives: Alternative[];
};

/**
 * Changing source from inside the reader (Master §26.16, INV-25).
 *
 * Switching is manual, the alternatives are same-language only, and the layouts are never claimed to
 * agree. Where the other source's copy of this unit was found confidently, it can be opened at its
 * start or at an *approximate* position — approximate is what it says, because OneShelf does not map
 * pages across sources. Where it was not found, this says so and offers that source's own track: the
 * one thing it will not do is guess.
 */
export function SourceSwitch({ offer, onStart, onApproximate, onClose, workId }: {
  offer: Alternatives;
  onStart: (alternative: Alternative) => void;
  onApproximate: (alternative: Alternative) => void;
  onClose: () => void;
  workId: string;
}) {
  const { t } = useI18n();
  return (
    <Drawer title={t("reader.changeSource")} onClose={onClose}>
      <p className="notice notice--info">{t("reader.changeSource.warning")}</p>
      {offer.alternatives.length === 0 ? (
        <p className="cards__meta">{t("reader.changeSource.none")}</p>
      ) : (
        <ul className="tracks">
          {offer.alternatives.map((alternative) => (
            <li key={alternative.track_id} className="tracks__row">
              <span className="tracks__name">
                {alternative.source_id} · {languageName(alternative.language)}
              </span>
              {alternative.confident ? (
                <>
                  <span className="tracks__count">{alternative.unit_title}</span>
                  <div className="firstrun__actions">
                    <button type="button" className="button" onClick={() => onStart(alternative)}>
                      {t("reader.changeSource.startUnit")}
                    </button>
                    <button type="button" className="button" onClick={() => onApproximate(alternative)}>
                      {t("reader.changeSource.approximate")}
                    </button>
                  </div>
                  <p className="panel__choiceHelp">{t("reader.changeSource.approximateHelp")}</p>
                </>
              ) : (
                <>
                  <p className="panel__choiceHelp">
                    {alternative.reason === "ambiguous"
                      ? t("reader.changeSource.ambiguous", { source: alternative.source_id })
                      : t("reader.changeSource.notFound", { source: alternative.source_id })}
                  </p>
                  {/* No equivalent unit, so the honest offer is the track itself (§26.16). */}
                  <Link className="button" to={`/works/${workId}?track=${alternative.track_id}`}>
                    {t("reader.changeSource.openTrack", { source: alternative.source_id })}
                  </Link>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  );
}
