import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { motion } from "motion/react";

import { ApiError, api } from "@/api/client";
import { CoverPlaceholder } from "@/components/CoverPlaceholder";
import { LoadingState } from "@/components/LoadingState";
import { useResource } from "@/api/useApi";
import type { Track, Unit, WorkDetails } from "@/api/types";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";
import { handleTabKeys } from "@/components/tabKeyboard";
import { languageName } from "@/i18n/language";
import { TRANSITION_EASE, useReducedMotion } from "@/lib/motion";
import { ExportWizard } from "@/features/export/ExportWizard";
import { ModalSurface } from "@/components/ModalSurface";
import { RemoveFromShelf } from "@/features/shelf/RemoveFromShelf";
import type { RemovalSummary } from "@/features/shelf/RemoveFromShelf";
import { readerLink } from "@/features/reader/links";
import { bytes } from "@/lib/format";
import { WorkNotes } from "./WorkNotes";

type Tab = "read" | "details" | "sources";
type CatalogAttempt = { trackId: string; status: string; reason: string | null };
type CatalogRefresh = { state: string; unit_count: number; reason: string | null };
const archivedTrack = (track: Track | null) => track?.kind === "source"
  && track.listing_id === null && track.availability === "unavailable";
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
  const [completedOffer, setCompletedOffer] = useState<{
    workId: string; generation: number; summary: RemovalSummary;
  } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [completion, setCompletion] = useState<{ workId: string; value: boolean } | null>(null);
  const [summaryProblem, setSummaryProblem] = useState<{ workId: string; generation: number } | null>(null);
  const completionRequest = useRef({ workId: id, generation: 0, completed: false });
  if (completionRequest.current.workId !== id) {
    completionRequest.current = { workId: id, generation: completionRequest.current.generation + 1,
      completed: false };
  }
  useEffect(() => {
    setCompletedOffer(null);
    setSummaryProblem(null);
  }, [id]);
  const { data, error, reload } = useResource<WorkDetails>(`/api/works/${id}`,
    trackId ? { track_id: trackId } : undefined);
  const [problem, setProblem] = useState<string | null>(null);
  const reduced = useReducedMotion();
  const location = useLocation();
  const alreadyChecked = useRef(new Set<string>());
  const openedAttempt = (location.state as { catalogAttempt?: CatalogAttempt } | null)?.catalogAttempt ?? null;
  const [catalogAttempt, setCatalogAttempt] = useState<CatalogAttempt | null>(null);
  const selectedTrackId = data?.selected_track_id ?? null;
  const selectedAttempt = catalogAttempt?.trackId === selectedTrackId ? catalogAttempt
    : openedAttempt?.trackId === selectedTrackId ? openedAttempt : null;

  const refreshCatalog = useCallback(async (selected: Track) => {
    setCatalogAttempt({ trackId: selected.id, status: "checking", reason: null });
    try {
      const result = await api.post<CatalogRefresh>(`/api/tracks/${selected.id}/catalog/refresh`);
      const status = result.state === "incomplete" || result.state === "suspicious" ? result.state
        : result.state === "trusted" || result.state === "unchanged" || result.state === "recovered"
          ? result.unit_count > 0 ? "loaded" : "empty" : "failed";
      setCatalogAttempt({ trackId: selected.id, status, reason: result.reason });
      reload();
    } catch (error) {
      const status = error instanceof ApiError && error.code === "SESSION_REQUIRED" ? "session_required"
        : error instanceof ApiError && error.code === "RATE_LIMITED" ? "rate_limited" : "failed";
      setCatalogAttempt({ trackId: selected.id, status, reason: error instanceof ApiError ? error.code : null });
    }
  }, [reload]);

  useEffect(() => {
    if (data === null || data.units.length > 0 || data.selected_track_id === null ||
        (trackId !== null && data.selected_track_id !== trackId)) return;
    const selected = data.tracks.find(track => track.id === data.selected_track_id);
    if (selected?.kind !== "source" || archivedTrack(selected)) return;
    const key = `${id}:${selected.id}`;
    if (alreadyChecked.current.has(key)) return;
    alreadyChecked.current.add(key);
    if (openedAttempt?.trackId === selected.id) return;
    void refreshCatalog(selected);
  }, [data, id, openedAttempt?.trackId, refreshCatalog, trackId]);

  if (error !== null) {
    return (
      <section className="screen">
        <p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button>
      </section>
    );
  }
  if (data === null) {
    return <section className="screen"><LoadingState /></section>;
  }
  if (trackId !== null && data.selected_track_id !== trackId) {
    return <section className="screen">
      <p className="notice notice--problem" role="alert">{t("work.trackUnavailable")}</p>
      <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button>
    </section>;
  }

  const { work, shelf, follow, tracks, units, continue_unit_id: continueUnit } = data;
  const completed = completion?.workId === id ? completion.value : shelf.completed;
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

  const completionIsCurrent = (workId: string, generation: number) => {
    const current = completionRequest.current;
    return current.workId === workId && current.generation === generation && current.completed;
  };

  const loadCompletionSummary = async (workId: string, generation: number) => {
    if (!completionIsCurrent(workId, generation)) return;
    try {
      const summary = await api.get<RemovalSummary>(`/api/shelf/${workId}/removal-summary`);
      if (!completionIsCurrent(workId, generation)) return;
      setSummaryProblem(null);
      if (summary.files > 0) setCompletedOffer({ workId, generation, summary });
    } catch {
      if (completionIsCurrent(workId, generation)) setSummaryProblem({ workId, generation });
    }
  };

  /** Completed keeps the work, its status and its progress; deleting the files is only ever offered. */
  const markCompleted = async (next: boolean) => {
    const workId = id;
    const generation = ++completionRequest.current.generation;
    completionRequest.current.completed = false;
    setNotice(null);
    setProblem(null);
    setSummaryProblem(null);
    setCompletedOffer(null);
    try {
      await api.post(`/api/shelf/${workId}`, { completed: next });
    } catch (error) {
      if (completionRequest.current.workId === workId && completionRequest.current.generation === generation)
        setProblem(error instanceof ApiError ? error.message : t("state.offline"));
      return;
    }
    if (completionRequest.current.workId !== workId || completionRequest.current.generation !== generation) return;
    completionRequest.current.completed = next;
    setCompletion({ workId, value: next });
    reload();
    if (next) {
      setNotice(t("shelf.completed.title"));
      await loadCompletionSummary(workId, generation);
    }
  };

  return (
    <article className="screen work">
      <motion.header className="work__header"
        initial={reduced ? false : { opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={TRANSITION_EASE}
      >
        <WorkCover url={data.cover_url ?? null} title={work.title} />
        <div className="work__intro">
          <h1 className="work__title display" dir="auto">{work.title}</h1>
          {work.original_title && <p className="work__original" dir="auto">{work.original_title}</p>}
          <p className="work__meta">
            {work.content_type && <span>{typeLabel(work.content_type, t)}</span>}
            {work.creator && <span dir="auto">{work.creator}</span>}
            {current && <span>{languageName(current.language, language)}</span>}
          </p>
          <div className="work__actions">
            {continueUnit && (
              <Link className="button button--primary" to={readerLink(continueUnit, id, data.selected_track_id)}>{t("work.continue")}</Link>
            )}
            {shelf.on_shelf ? (
              <>
                <button type="button" className="button" onClick={() => void startRemoval()}>
                  {t("shelf.remove.action")}
                </button>
                <button type="button" className="button" aria-pressed={completed}
                        onClick={() => void markCompleted(!completed)}>
                  {completed ? t("shelf.completed.undo") : t("shelf.completed.action")}
                </button>
              </>
            ) : (
              <button type="button" className="button" onClick={() => toggle(api.post(`/api/shelf/${id}`))}>
                {t("work.addShelf")}
              </button>
            )}
            <button type="button" className="button" aria-pressed={selectedFollowing}
                    disabled={current === null || (archivedTrack(current) && !selectedFollowing)}
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
            <button type="button" className="button work__toggle" aria-pressed={shelf.favorite}
                    onClick={() => toggle(api.post(`/api/shelf/${id}`, { favorite: !shelf.favorite }))}>
              <span className="work__toggleMark" aria-hidden="true"><svg viewBox="0 0 16 16" fill="none">
                <path d="m3 8 3.2 3.2L13 4.5" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
              </svg></span>
              {t("work.favorite")}
            </button>
            <button type="button" className="button work__toggle" aria-pressed={shelf.pinned}
                    onClick={() => toggle(api.post(`/api/shelf/${id}`, { pinned: !shelf.pinned }))}>
              <span className="work__toggleMark" aria-hidden="true"><svg viewBox="0 0 16 16" fill="none">
                <path d="m3 8 3.2 3.2L13 4.5" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
              </svg></span>
              {t("work.pin")}
            </button>
            <button type="button" className="button" onClick={() => setExporting(true)}>{t("export.open")}</button>
          </div>
          {work.description && <p className="work__description" dir="auto">{work.description}</p>}
        </div>
      </motion.header>

      <div className="toolbar__tabs" role="tablist" aria-label={t("work.tab.details")} onKeyDown={handleTabKeys}>
        {(["read", "details", "sources"] as Tab[]).map((candidate) => (
          <button key={candidate} type="button" role="tab" className="chip" aria-selected={tab === candidate}
                  tabIndex={tab === candidate ? 0 : -1}
                  id={`work-tab-${candidate}`} aria-controls="work-tabpanel"
                  onClick={() => setTab(candidate)}>
            {t(`work.tab.${candidate}` as const)}
          </button>
        ))}
      </div>

      {notice !== null && <p className="notice" role="status">{notice}</p>}
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {summaryProblem?.workId === id && summaryProblem.generation === completionRequest.current.generation
        && completed && <div className="notice notice--problem">
        <p role="alert">{t("shelf.completed.summaryFailed")}</p>
        <button type="button" className="button"
                onClick={() => void loadCompletionSummary(summaryProblem.workId, summaryProblem.generation)}>
          {t("shelf.completed.retrySummary")}
        </button>
      </div>}

      {removing !== null && (
        <RemoveFromShelf title={work.title} summary={removing}
                         onKeep={() => void remove(false)}
                         onDelete={() => void remove(true)}
                         onCancel={() => setRemoving(null)} />
      )}

      {completedOffer?.workId === id && completedOffer.generation === completionRequest.current.generation
        && completed && (
        <ModalSurface className="confirm" title={t("shelf.completed.title")}
                      onClose={() => setCompletedOffer(null)}>
          <h2 className="display">{t("shelf.completed.title")}</h2>
          <p>{t("shelf.completed.body", { title: work.title })}</p>
          <p>{t("shelf.completed.offer", { files: completedOffer.summary.files,
            size: bytes(completedOffer.summary.bytes) })}</p>
          <div className="confirm__actions">
            <button type="button" className="button button--primary" onClick={() => setCompletedOffer(null)}>
              {t("shelf.completed.keep")}
            </button>
            <button type="button" className="button"
                    onClick={() => {
                      if (!completionIsCurrent(completedOffer.workId, completedOffer.generation)) return;
                      setCompletedOffer(null);
                      void toggle(api.delete<{ deleted_files: number }>(`/api/works/${completedOffer.workId}/files`)
                        .then((done) => setNotice(t("shelf.filesDeleted", { files: done.deleted_files }))));
                    }}>
              {t("shelf.completed.delete")}
            </button>
          </div>
        </ModalSurface>
      )}

      {/* The tabs switch this one panel, and say so — a tab that controls nothing announces nothing. */}
      <div role="tabpanel" id="work-tabpanel" aria-labelledby={`work-tab-${tab}`} tabIndex={-1}>
        <div hidden={tab !== "read"}>
          <UnitIndex units={units} workId={id} trackId={data.selected_track_id}
            downloadable={current !== null && !archivedTrack(current)} track={current}
            attempt={selectedAttempt} onRetry={() => { if (current) void refreshCatalog(current); }}
            onLanguages={() => setTab("sources")} />
        </div>
        {tab === "details" && <><Details data={data} /><WorkNotes workId={id} /></>}
        {tab === "sources" && (
          <Sources tracks={tracks} selected={data.selected_track_id} onChoose={(track) => {
            const next = new URLSearchParams(search);
            next.set("track", track.id);
            setSearch(next);
          }}
                   workId={id} onOpened={(openedTrackId) => {
                     const next = new URLSearchParams(search);
                     next.set("track", openedTrackId);
                     setSearch(next);
                   }}
                   attempt={selectedAttempt} onRefresh={refreshCatalog} onRefreshed={reload} />
        )}
      </div>
      {exporting && <ExportWizard workId={id} trackId={data.selected_track_id}
                                   onClose={() => setExporting(false)} />}
    </article>
  );
}

function UnitIndex({ units, workId, trackId, downloadable, track, attempt, onRetry, onLanguages }: {
  units: Unit[]; workId: string; trackId: string | null; downloadable: boolean;
  track: Track | null; attempt: CatalogAttempt | null; onRetry: () => void; onLanguages: () => void;
}) {
  const { t } = useI18n();
  const [problem, setProblem] = useState<string | null>(null);
  const [queueing, setQueueing] = useState(false);
  const [requested, setRequested] = useState<string[]>([]);
  useEffect(() => { setRequested([]); setProblem(null); }, [workId, trackId]);
  const eligible = units.filter(unit => unit.availability !== "unavailable" && !unit.downloaded && !requested.includes(unit.id));
  const queueAll = async () => {
    const ids = eligible.map(unit => unit.id);
    if (ids.length === 0) return;
    setProblem(null);
    setQueueing(true);
    try {
      // A download batch accepts at most 2,000 unit IDs. One click can queue larger catalogues.
      for (let start = 0; start < ids.length; start += 2000) {
        const batch = ids.slice(start, start + 2000);
        await api.post("/api/downloads", { unit_ids: batch });
        setRequested(current => [...current, ...batch]);
      }
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      setQueueing(false);
    }
  };
  if (units.length === 0) return <CatalogStatus track={track} attempt={attempt}
    onRetry={onRetry} onLanguages={onLanguages} />;

  return (
    <>
    {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
    <div className="units__bulk">
      {downloadable && track?.kind !== "local" && eligible.length > 0 && <button type="button" className="button" disabled={queueing}
        aria-busy={queueing} onClick={() => void queueAll()}>{t("work.downloadAll")}</button>}
      {requested.length > 0 && <p role="status" className="cards__meta">{requested.length === 1
        ? t("work.downloadRequestedOne") : t("work.downloadRequested", { count: requested.length })}</p>}
    </div>
    <ul className="units" aria-label={t("work.units")}>
      {units.map((unit) => (
        <li key={unit.id} className="units__row">
          <Link className="units__link" to={readerLink(unit.id, workId, trackId)}>
            <span className="units__number">{unit.number ?? ""}</span>
            <span className="units__title" dir="auto">{unit.title ?? unit.id}</span>
          </Link>
          <span className="units__state">
            {unit.read_state === "read" ? t("work.finished")
              : unit.read_state === "partial" ? `${Math.round(unit.fraction * 100)}%` : t("work.unread")}
          </span>
          {unit.downloaded
            ? <span className="units__badge">{t("work.downloaded")}</span>
            : requested.includes(unit.id) ? <span className="units__badge">{t("work.requested")}</span>
            : downloadable && <button type="button" className="units__action"
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

function CatalogStatus({ track, attempt, onRetry, onLanguages, showActions = true }: {
  track: Track | null; attempt: CatalogAttempt | null; onRetry: () => void;
  onLanguages: () => void; showActions?: boolean;
}) {
  const { t, language } = useI18n();
  if (archivedTrack(track)) return <p className="notice">{t("work.track.archived")}</p>;
  if (track?.kind !== "source") return <p className="notice">{t("work.noUnits")}</p>;
  const status = attempt?.status ?? "checking";
  const problem = !["checking", "empty"].includes(status);
  const message: StringKey = status === "checking" ? "work.catalog.checking"
    : status === "empty" ? "work.catalog.empty"
    : status === "incomplete" ? "work.catalog.incomplete"
    : status === "session_required" ? "work.catalog.reconnect"
    : status === "rate_limited" ? "work.catalog.rateLimited"
    : status === "suspicious" ? "work.catalog.suspicious"
    : status === "unsupported" ? "work.catalog.unsupported" : "work.catalog.failed";
  return <div className={`notice${problem ? " notice--problem" : ""}`}>
    <p role={problem ? "alert" : "status"}>{t(message, { language: languageName(track.language, language) })}</p>
    {showActions && status !== "checking" && <div className="work__actions">
      <button type="button" className="button" onClick={onRetry}>{t("work.catalog.retry")}</button>
      {status === "empty" && <button type="button" className="button" onClick={onLanguages}>
        {t("work.track.findLanguages")}
      </button>}
      {status === "session_required" && <Link className="button" to="/sources">{t("work.catalog.sources")}</Link>}
    </div>}
  </div>;
}

function Details({ data }: { data: WorkDetails }) {
  const { t } = useI18n();
  const { work } = data;
  return (
    <dl className="details">
      {work.creator && <><dt>{t("work.detail.creator")}</dt><dd dir="auto">{work.creator}</dd></>}
      {work.content_type && <><dt>{t("work.detail.type")}</dt><dd>{typeLabel(work.content_type, t)}</dd></>}
      {work.aliases.length > 0 && <><dt>{t("work.detail.aliases")}</dt><dd>
        {work.aliases.map((alias, index) => <span key={`${alias}-${index}`}>
          {index > 0 && " · "}<bdi>{alias}</bdi>
        </span>)}
      </dd></>}
      {work.description && <><dt>{t("work.detail.description")}</dt><dd dir="auto">{work.description}</dd></>}
    </dl>
  );
}

type ReadingLanguages = {
  source_id: string; listing_key: string; title: string; content_type: string | null; languages: string[];
};

function Sources({ tracks, selected, workId, attempt, onChoose, onOpened, onRefresh, onRefreshed }: {
  tracks: Track[];
  selected: string | null;
  workId: string;
  attempt: CatalogAttempt | null;
  onChoose: (track: Track) => void;
  onOpened: (trackId: string) => void;
  onRefresh: (track: Track) => Promise<void>;
  onRefreshed: () => void;
}) {
  const { t, language } = useI18n();
  const [finding, setFinding] = useState(false);
  const [opening, setOpening] = useState(false);
  const [readingLanguages, setReadingLanguages] = useState<{ trackId: string; value: ReadingLanguages } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  // What the empty state tells a person to do, and what a first open that could not reach the source leaves
  // to try again: ask the selected source for its catalogue now.
  const refresh = async (track: Track) => {
    setProblem(null);
    await onRefresh(track);
  };

  const findLanguages = async (track: Track) => {
    setFinding(true);
    setProblem(null);
    try {
      const value = await api.get<ReadingLanguages>(`/api/tracks/${track.id}/languages`);
      setReadingLanguages({ trackId: track.id, value });
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      setFinding(false);
    }
  };

  const openLanguage = async (choice: string, listing: ReadingLanguages) => {
    setOpening(true);
    setProblem(null);
    try {
      const opened = await api.post<{ work_id: string; track_id: string; catalog: string }>("/api/listings/open", {
        source_id: listing.source_id, listing_key: listing.listing_key, title: listing.title,
        content_type: listing.content_type, language: choice,
      });
      if (opened.work_id !== workId) throw new Error("Unexpected work");
      if (opened.catalog === "empty") {
        setProblem(t("work.track.noReadableChapters"));
        return;
      }
      if (opened.catalog !== "refreshed" && opened.catalog !== "present") {
        setProblem(t("work.track.openFailed"));
        return;
      }
      setReadingLanguages(null);
      if (opened.track_id === selected) onRefreshed();
      else onOpened(opened.track_id);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("work.track.openFailed"));
    } finally {
      setOpening(false);
    }
  };

  const current = tracks.find(track => track.id === selected) ?? null;
  const choices = readingLanguages?.trackId === selected ? readingLanguages.value : null;
  const editionLabel = (track: Track) => {
    if (track.listing_title && track.listing_key) return `${track.listing_title} · #${track.listing_key}`;
    if (track.listing_key) return `#${track.listing_key}`;
    return track.listing_title ?? null;
  };

  return (
    <>
    {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
    {current?.unit_count === 0 && attempt !== null &&
      <CatalogStatus track={current} attempt={attempt} onRetry={() => {}}
        onLanguages={() => {}} showActions={false} />}
    <ul className="tracks">
      {tracks.map((track) => (
        <li key={track.id} className="tracks__row">
          <span className="tracks__name">
            <span><bdi>{track.source_id}</bdi> · {languageName(track.language, language)}</span>
            {editionLabel(track) && <span className="tracks__edition" dir="auto">{editionLabel(track)}</span>}
            {archivedTrack(track) && <span className="tracks__edition">{t("work.track.archived")}</span>}
          </span>
          <span className="tracks__count">{track.unit_count}</span>
          {track.id === selected ? (
            <>
              <span className="chip chip--static">{t("work.track.current")}</span>
              {track.kind === "source" && !archivedTrack(track) && (
                <button type="button" className="button" disabled={attempt?.status === "checking"}
                  onClick={() => void refresh(track)}>
                  {t("work.track.refresh")}
                </button>
              )}
              {track.kind === "source" && !archivedTrack(track) && track.unit_count === 0 && (
                <button type="button" className="button" disabled={finding || opening}
                  onClick={() => void findLanguages(track)}>{t("work.track.findLanguages")}</button>
              )}
            </>
          ) : (
            <button type="button" className="button"
                    aria-label={`${t("work.track.use")}: ${track.source_id} · ${languageName(track.language, language)}`
                      + `${editionLabel(track) ? ` · ${editionLabel(track)}` : ""}`}
                    onClick={() => onChoose(track)}>
              {t("work.track.use")}
            </button>
          )}
        </li>
      ))}
    </ul>
    {choices !== null && <div className="notice" role="status">
      {choices.languages.length === 0 ? t("work.track.noLanguages") : <>
        <p>{t("work.track.availableLanguages")}</p>
        <div className="work__actions">
          {choices.languages.map((choice) => (
            <button key={choice} type="button" className="button" disabled={opening}
              onClick={() => void openLanguage(choice, choices)}>{languageName(choice, language)}</button>
          ))}
        </div>
      </>}
    </div>}
    </>
  );
}


/** The selected track's cover (presentation only, INV-28); a typographic cover when art is unavailable. */
function WorkCover({ url, title }: { url: string | null; title: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  return (
    <div className="work__cover" aria-hidden="true">
      {url && failed !== url
        ? <img src={url} alt="" onError={() => setFailed(url)} />
        : <CoverPlaceholder title={title} className="work__blank" />}
    </div>
  );
}
