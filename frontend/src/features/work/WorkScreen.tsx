import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { ApiError, api } from "@/api/client";
import { useResource } from "@/api/useApi";
import type { Track, Unit, WorkDetails } from "@/api/types";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";
import { languageName } from "@/i18n/language";
import { ExportWizard } from "@/features/export/ExportWizard";
import { ModalSurface } from "@/components/ModalSurface";
import { RemoveFromShelf } from "@/features/shelf/RemoveFromShelf";
import type { RemovalSummary } from "@/features/shelf/RemoveFromShelf";
import { readerLink } from "@/features/reader/links";
import { bytes } from "@/lib/format";

type Tab = "read" | "details" | "sources";
const CONTENT_TYPES = ["manga", "manhwa", "manhua", "comic", "book", "paper"];
function typeLabel(value: string, t: ReturnType<typeof useI18n>["t"]): string {
  return CONTENT_TYPES.includes(value) ? t(`work.type.${value}` as StringKey) : value.replaceAll("_", " ");
}

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
  const { t, language } = useI18n();
  const [tab, setTab] = useState<Tab>("read");
  // The reader can send someone here to a *named* track when it could not find their unit there (§26.16).
  const [search, setSearch] = useSearchParams();
  const trackId = search.get("track");
  const [exporting, setExporting] = useState(false);
  const [removing, setRemoving] = useState<RemovalSummary | null>(null);
  const [completedOffer, setCompletedOffer] = useState<RemovalSummary | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { data, error, reload } = useResource<WorkDetails>(`/api/works/${id}`,
    trackId ? { track_id: trackId } : undefined);
  const [problem, setProblem] = useState<string | null>(null);

  if (error !== null) {
    return (
      <section className="screen">
        <p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button>
      </section>
    );
  }
  if (data === null) {
    return <section className="screen"><p className="screen__subtitle">{t("state.loading")}</p></section>;
  }

  const { work, shelf, follow, tracks, units, continue_unit_id: continueUnit } = data;
  const current = tracks.find((track) => track.id === data.selected_track_id) ?? null;
  const selectedFollowing = current !== null && follow.following && follow.track_id === current.id;

  const toggle = async (call: Promise<unknown>) => {
    setProblem(null);
    try {
      await call;
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      reload();
    }
  };

  /**
   * Removing from the Shelf (§22, §47). The facts come from the library, never from a guess here, and
   * the confirmation only appears when there is something to lose — §22 asks for it when files or
   * progress exist. Deleting the files is its own choice; Follow and progress are untouched either way
   * (§23, INV-10).
   */
  const startRemoval = async () => {
    setNotice(null);
    try {
      const summary = await api.get<RemovalSummary>(`/api/shelf/${id}/removal-summary`);
      if (summary.files === 0 && !summary.has_progress) {
        await remove(false);
        return;
      }
      setRemoving(summary);
    } catch {
      setNotice(t("state.offline"));
    }
  };

  const remove = async (deleteFiles: boolean) => {
    setRemoving(null);
    try {
      // The count comes from the library's answer, never from the forecast: a file OneShelf refuses to
      // touch is not deleted, and claiming otherwise on a destructive path would be a lie (§47).
      const done = await api.delete<{ deleted_files?: number }>(`/api/shelf/${id}?delete_files=${deleteFiles}`);
      const deleted = done?.deleted_files ?? 0;
      setNotice(deleteFiles ? `${t("shelf.removed")} ${t("shelf.filesDeleted", { files: deleted })}`
                            : t("shelf.removed"));
    } catch {
      setNotice(t("state.offline"));
    } finally {
      reload();
    }
  };

  /** Completed keeps the work, its status and its progress; deleting the files is only ever offered. */
  const markCompleted = async (completed: boolean) => {
    setNotice(null);
    try {
      await api.post(`/api/shelf/${id}`, { completed });
      if (!completed) return;
      const summary = await api.get<RemovalSummary>(`/api/shelf/${id}/removal-summary`);
      if (summary.files > 0) setCompletedOffer(summary);
    } catch {
      setNotice(t("state.offline"));
    } finally {
      reload();
    }
  };

  return (
    <article className="screen work">
      <header className="work__header">
        <WorkCover url={data.cover_url ?? null} />
        <div className="work__intro">
          <h1 className="work__title display">{work.title}</h1>
          {work.original_title && <p className="work__original">{work.original_title}</p>}
          <p className="work__meta">
            {work.content_type && <span>{typeLabel(work.content_type, t)}</span>}
            {work.creator && <span>{work.creator}</span>}
            {current && <span>{languageName(current.language, language)}</span>}
          </p>
          {work.description && <p className="work__description">{work.description}</p>}
          <div className="work__actions">
            {continueUnit && (
              <Link className="button button--primary" to={readerLink(continueUnit, id, data.selected_track_id)}>{t("work.continue")}</Link>
            )}
            {shelf.on_shelf ? (
              <>
                <button type="button" className="button" onClick={() => void startRemoval()}>
                  {t("shelf.remove.action")}
                </button>
                <button type="button" className="button" aria-pressed={shelf.completed}
                        onClick={() => void markCompleted(!shelf.completed)}>
                  {shelf.completed ? t("shelf.completed.undo") : t("shelf.completed.action")}
                </button>
              </>
            ) : (
              <button type="button" className="button" onClick={() => toggle(api.post(`/api/shelf/${id}`))}>
                {t("work.addShelf")}
              </button>
            )}
            <button type="button" className="button" aria-pressed={selectedFollowing}
                    disabled={current === null}
                    onClick={() => {
                      if (current === null) return;
                      void toggle(selectedFollowing
                        ? api.delete(`/api/follows/${id}?${new URLSearchParams({ language: current.language })}`)
                        : follow.following && follow.language === current.language
                        ? api.post(`/api/follows/${id}/preferred-source`, { language: current.language,
                          source_id: current.source_id, track_id: current.id })
                        : api.post(`/api/follows/${id}`, { language: current.language,
                          source_id: current.source_id, track_id: current.id }));
                    }}>
              {selectedFollowing ? t("work.unfollow") : t("work.follow")}
            </button>
            <button type="button" className="button" aria-pressed={shelf.favorite}
                    onClick={() => toggle(api.post(`/api/shelf/${id}`, { favorite: !shelf.favorite }))}>
              {t("work.favorite")}
            </button>
            <button type="button" className="button" aria-pressed={shelf.pinned}
                    onClick={() => toggle(api.post(`/api/shelf/${id}`, { pinned: !shelf.pinned }))}>
              {t("work.pin")}
            </button>
            <button type="button" className="button" onClick={() => setExporting(true)}>{t("export.open")}</button>
          </div>
        </div>
      </header>

      <div className="toolbar__tabs" role="tablist" aria-label={t("work.tab.details")}>
        {(["read", "details", "sources"] as Tab[]).map((candidate) => (
          <button key={candidate} type="button" role="tab" className="chip" aria-selected={tab === candidate}
                  id={`work-tab-${candidate}`} aria-controls="work-tabpanel"
                  onClick={() => setTab(candidate)}>
            {t(`work.tab.${candidate}` as const)}
          </button>
        ))}
      </div>

      {notice !== null && <p className="notice" role="status">{notice}</p>}
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}

      {removing !== null && (
        <RemoveFromShelf title={work.title} summary={removing}
                         onKeep={() => void remove(false)}
                         onDelete={() => void remove(true)}
                         onCancel={() => setRemoving(null)} />
      )}

      {completedOffer !== null && (
        <ModalSurface className="confirm" title={t("shelf.completed.title")}
                      onClose={() => setCompletedOffer(null)}>
          <h2 className="display">{t("shelf.completed.title")}</h2>
          <p>{t("shelf.completed.body", { title: work.title })}</p>
          <p>{t("shelf.completed.offer", { files: completedOffer.files, size: bytes(completedOffer.bytes) })}</p>
          <div className="confirm__actions">
            <button type="button" className="button button--primary" onClick={() => setCompletedOffer(null)}>
              {t("shelf.completed.keep")}
            </button>
            <button type="button" className="button"
                    onClick={() => {
                      setCompletedOffer(null);
                      void toggle(api.delete<{ deleted_files: number }>(`/api/works/${id}/files`)
                        .then((done) => setNotice(t("shelf.filesDeleted", { files: done.deleted_files }))));
                    }}>
              {t("shelf.completed.delete")}
            </button>
          </div>
        </ModalSurface>
      )}

      {/* The tabs switch this one panel, and say so — a tab that controls nothing announces nothing. */}
      <div role="tabpanel" id="work-tabpanel" aria-labelledby={`work-tab-${tab}`} tabIndex={-1}>
        {tab === "read" && <UnitIndex units={units} workId={id} trackId={data.selected_track_id} />}
        {tab === "details" && <Details data={data} />}
        {tab === "sources" && (
          <Sources tracks={tracks} selected={data.selected_track_id} onChoose={(track) => {
            const next = new URLSearchParams(search);
            next.set("track", track.id);
            setSearch(next);
          }}
                   onRefreshed={reload} />
        )}
      </div>
      {exporting && <ExportWizard workId={id} trackId={data.selected_track_id}
                                   onClose={() => setExporting(false)} />}
    </article>
  );
}

function UnitIndex({ units, workId, trackId }: { units: Unit[]; workId: string; trackId: string | null }) {
  const { t } = useI18n();
  const [problem, setProblem] = useState<string | null>(null);
  if (units.length === 0) return <p className="notice">{t("work.noUnits")}</p>;

  return (
    <>
    {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
    <ul className="units" aria-label={t("work.units")}>
      {units.map((unit) => (
        <li key={unit.id} className="units__row">
          <Link className="units__link" to={readerLink(unit.id, workId, trackId)}>
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
                      onClick={() => {
                        setProblem(null);
                        void api.post("/api/downloads", { unit_ids: [unit.id] }).catch((error: unknown) =>
                          setProblem(error instanceof ApiError ? error.message : t("state.offline")));
                      }}>
                {t("work.download")}
              </button>}
        </li>
      ))}
    </ul>
    </>
  );
}

function Details({ data }: { data: WorkDetails }) {
  const { t } = useI18n();
  const { work } = data;
  return (
    <dl className="details">
      {work.creator && <><dt>{t("work.detail.creator")}</dt><dd>{work.creator}</dd></>}
      {work.content_type && <><dt>{t("work.detail.type")}</dt><dd>{typeLabel(work.content_type, t)}</dd></>}
      {work.aliases.length > 0 && <><dt>{t("work.detail.aliases")}</dt><dd>{work.aliases.join(" · ")}</dd></>}
      {work.description && <><dt>{t("work.detail.description")}</dt><dd>{work.description}</dd></>}
    </dl>
  );
}

function Sources({ tracks, selected, onChoose, onRefreshed }: {
  tracks: Track[];
  selected: string | null;
  onChoose: (track: Track) => void;
  onRefreshed: () => void;
}) {
  const { t, language } = useI18n();
  const [refreshing, setRefreshing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  // What the empty state tells a person to do, and what a first open that could not reach the source leaves
  // to try again: ask the selected source for its catalogue now.
  const refresh = async (track: Track) => {
    setRefreshing(true);
    setProblem(null);
    try {
      await api.post(`/api/tracks/${track.id}/catalog/refresh`);
      onRefreshed();
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <>
    {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
    <ul className="tracks">
      {tracks.map((track) => (
        <li key={track.id} className="tracks__row">
          <span className="tracks__name">{track.source_id} · {languageName(track.language, language)}</span>
          <span className="tracks__count">{track.unit_count}</span>
          {track.id === selected ? (
            <>
              <span className="chip chip--static">{t("work.track.current")}</span>
              {track.kind === "source" && (
                <button type="button" className="button" disabled={refreshing} onClick={() => void refresh(track)}>
                  {t("work.track.refresh")}
                </button>
              )}
            </>
          ) : (
            <button type="button" className="button"
                    aria-label={`${t("work.track.use")}: ${track.source_id} · ${languageName(track.language, language)}`}
                    onClick={() => onChoose(track)}>
              {t("work.track.use")}
            </button>
          )}
        </li>
      ))}
    </ul>
    </>
  );
}


/** The selected track's cover (presentation only, INV-28); the paper placeholder when there is none or it fails. */
function WorkCover({ url }: { url: string | null }) {
  const [failed, setFailed] = useState<string | null>(null);
  return (
    <div className="work__cover" aria-hidden="true">
      {url && failed !== url && <img src={url} alt="" onError={() => setFailed(url)} />}
    </div>
  );
}
