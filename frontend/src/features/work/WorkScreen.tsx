import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import type { Track, Unit, WorkDetails } from "@/api/types";
import { useI18n } from "@/i18n/i18n";

type Tab = "read" | "details" | "sources";

/**
 * Work Details (Master §32.8).
 *
 * A smaller hero-like header, a few primary actions, and three tabs. The Reading Unit list is an
 * elegant index, not a technical table: it keeps the source's own order and numbering — a Prologue
 * stays a Prologue and 3.5 stays 3.5 (INV-24). Changing source or language happens only when asked.
 */
export function WorkScreen({ workId }: { workId?: string }) {
  const params = useParams();
  const id = workId ?? params.workId ?? "";
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("read");
  const [trackId, setTrackId] = useState<string | null>(null);
  const { data, error, reload } = useResource<WorkDetails>(`/api/works/${id}`,
    trackId ? { track_id: trackId } : undefined);

  if (error !== null) {
    return (
      <section className="screen">
        <p className="notice notice--problem" role="alert">{error}</p>
      </section>
    );
  }
  if (data === null) {
    return <section className="screen"><p className="screen__subtitle">{t("state.loading")}</p></section>;
  }

  const { work, shelf, follow, tracks, units, continue_unit_id: continueUnit } = data;
  const current = tracks.find((track) => track.id === data.selected_track_id) ?? null;

  const toggle = async (call: Promise<unknown>) => {
    try {
      await call;
    } finally {
      reload();
    }
  };

  return (
    <article className="screen work">
      <header className="work__header">
        <div className="work__cover" aria-hidden="true" />
        <div className="work__intro">
          <h1 className="work__title display">{work.title}</h1>
          {work.original_title && <p className="work__original">{work.original_title}</p>}
          <p className="work__meta">
            {work.content_type && <span>{work.content_type}</span>}
            {work.creator && <span>{work.creator}</span>}
            {current && <span>{languageName(current.language)}</span>}
          </p>
          {work.description && <p className="work__description">{work.description}</p>}
          <div className="work__actions">
            {continueUnit && (
              <Link className="button button--primary" to={`/read/${continueUnit}`}>{t("work.continue")}</Link>
            )}
            {shelf.on_shelf ? (
              <span className="chip chip--static">{t("work.onShelf")}</span>
            ) : (
              <button type="button" className="button" onClick={() => toggle(api.post(`/api/shelf/${id}`))}>
                {t("work.addShelf")}
              </button>
            )}
            <button type="button" className="button" aria-pressed={follow.following}
                    onClick={() => toggle(follow.following ? api.delete(`/api/follows/${id}`)
                                                           : api.post(`/api/follows/${id}`))}>
              {follow.following ? t("work.unfollow") : t("work.follow")}
            </button>
            <button type="button" className="button" aria-pressed={shelf.favorite}
                    onClick={() => toggle(api.post(`/api/shelf/${id}`, { favorite: !shelf.favorite }))}>
              {t("work.favorite")}
            </button>
            <button type="button" className="button" aria-pressed={shelf.pinned}
                    onClick={() => toggle(api.post(`/api/shelf/${id}`, { pinned: !shelf.pinned }))}>
              {t("work.pin")}
            </button>
          </div>
        </div>
      </header>

      <div className="toolbar__tabs" role="tablist" aria-label={t("work.tab.details")}>
        {(["read", "details", "sources"] as Tab[]).map((candidate) => (
          <button key={candidate} type="button" role="tab" className="chip" aria-selected={tab === candidate}
                  onClick={() => setTab(candidate)}>
            {t(`work.tab.${candidate}` as const)}
          </button>
        ))}
      </div>

      {tab === "read" && <UnitIndex units={units} />}
      {tab === "details" && <Details data={data} />}
      {tab === "sources" && (
        <Sources tracks={tracks} selected={data.selected_track_id} onChoose={(track) => setTrackId(track.id)} />
      )}
    </article>
  );
}

function languageName(code: string): string {
  try {
    return new Intl.DisplayNames(undefined, { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}

function UnitIndex({ units }: { units: Unit[] }) {
  const { t } = useI18n();
  if (units.length === 0) return <p className="notice">{t("work.noUnits")}</p>;

  return (
    <ul className="units" aria-label={t("work.units")}>
      {units.map((unit) => (
        <li key={unit.id} className="units__row">
          <Link className="units__link" to={`/read/${unit.id}`}>
            <span className="units__number">{unit.number ?? ""}</span>
            <span className="units__title">{unit.title ?? unit.id}</span>
          </Link>
          <span className="units__state">
            {unit.read_state === "read" ? t("work.finished")
              : unit.read_state === "partial" ? `${Math.round(unit.fraction * 100)}%` : t("work.unread")}
          </span>
          {unit.downloaded
            ? <span className="units__badge">{t("work.downloaded")}</span>
            : <button type="button" className="units__action"
                      onClick={() => api.post("/api/downloads", { unit_ids: [unit.id] })}>
                {t("work.download")}
              </button>}
        </li>
      ))}
    </ul>
  );
}

function Details({ data }: { data: WorkDetails }) {
  const { work } = data;
  return (
    <dl className="details">
      {work.creator && <><dt>Creator</dt><dd>{work.creator}</dd></>}
      {work.content_type && <><dt>Type</dt><dd>{work.content_type}</dd></>}
      {work.aliases.length > 0 && <><dt>Also known as</dt><dd>{work.aliases.join(" · ")}</dd></>}
      {work.description && <><dt>Description</dt><dd>{work.description}</dd></>}
    </dl>
  );
}

function Sources({ tracks, selected, onChoose }: {
  tracks: Track[];
  selected: string | null;
  onChoose: (track: Track) => void;
}) {
  const { t } = useI18n();
  return (
    <ul className="tracks">
      {tracks.map((track) => (
        <li key={track.id} className="tracks__row">
          <span className="tracks__name">{track.source_id} · {languageName(track.language)}</span>
          <span className="tracks__count">{track.unit_count}</span>
          {track.id === selected ? (
            <span className="chip chip--static">{t("work.track.current")}</span>
          ) : (
            <button type="button" className="button"
                    aria-label={`${t("work.track.use")}: ${track.source_id} · ${languageName(track.language)}`}
                    onClick={() => onChoose(track)}>
              {t("work.track.use")}
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
