import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useResource } from "@/api/useApi";
import { Icon } from "@/components/Icon";
import { ModalSurface } from "@/components/ModalSurface";
import { LoadingState } from "@/components/LoadingState";
import type { ShelfResponse } from "@/api/types";
import { WorkCard } from "@/components/WorkCard";
import { ShelfCase } from "@/components/ShelfCase";
import { useShelfColumns } from "./useShelfColumns";
import { RemoveFromShelf } from "./RemoveFromShelf";
import type { RemovalSummary } from "./RemoveFromShelf";
import { ApiError, api } from "@/api/client";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";
import { handleTabKeys } from "@/components/tabKeyboard";
import { TagsDrawer } from "./TagsDrawer";

const VIEWS: { id: string; labelKey: StringKey }[] = [
  { id: "all", labelKey: "shelf.view.all" },
  { id: "saved", labelKey: "shelf.view.saved" },
  { id: "reading", labelKey: "shelf.view.reading" },
  { id: "completed", labelKey: "shelf.view.completed" },
  { id: "favorites", labelKey: "shelf.view.favorites" },
  { id: "pinned", labelKey: "shelf.view.pinned" },
];

/**
 * My Shelf (Master §22, §32.9): the strongest extension of the bookshelf motif after Home.
 * Search here is local only — it never reaches a source (§22, §7).
 */
export function ShelfScreen() {
  const { t, language } = useI18n();
  const { ref: shelfRef, columns } = useShelfColumns();
  const [view, setView] = useState("all");
  const [query, setQuery] = useState("");
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [sort, setSort] = useState<"added" | "title" | "last_read" | "progress" | "size">("added");
  const [managing, setManaging] = useState<{ work_id: string; title: string } | null>(null);
  const [removing, setRemoving] = useState<{ summary: RemovalSummary; title: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(false);
  const searchTerm = query.trim();
  const activeView = searchTerm ? "all" : view;
  const { data, error, loading, reload } = useResource<ShelfResponse>("/api/shelf",
    searchTerm ? { q: searchTerm } : { view });

  /**
   * §32.9: sorting is the screen's own work. The shelf arrives whole and local, so reordering it needs
   * no second request — and "added" is the order the library already gave, left exactly as it came.
   */
  const entries = useMemo(() => {
    const rows = data?.entries ?? [];
    if (sort === "added") return rows;
    const sorted = [...rows];
    if (sort === "title") return sorted.sort((a, b) => a.title.localeCompare(b.title, language));
    if (sort === "last_read") return sorted.sort((a, b) => (b.last_read_at ?? "").localeCompare(a.last_read_at ?? ""));
    if (sort === "progress") return sorted.sort((a, b) => b.read_fraction - a.read_fraction);
    if (sort === "size") return sorted.sort((a, b) => b.total_bytes - a.total_bytes);
    return rows;
  }, [data, sort, language]);

  const toggleSelect = useCallback((workId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(workId)) next.delete(workId); else next.add(workId);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelected(new Set(entries.map((e) => e.work_id)));
  }, [entries]);

  const exitBatch = useCallback(() => {
    setSelecting(false);
    setSelected(new Set());
  }, []);

  const batchAction = useCallback(async (action: string) => {
    if (selected.size === 0) return;
    setBatchBusy(true);
    setProblem(null);
    try {
      await api.post("/api/shelf/batch", { work_ids: [...selected], action });
      exitBatch();
      reload();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : t("state.offline"));
    } finally {
      setBatchBusy(false);
    }
  }, [selected, exitBatch, reload, t]);

  /** The same removal a work's own page offers, from a row, with the same facts and the same words. */
  const startRemoval = async (work_id: string, title: string) => {
    setProblem(null);
    setManaging(null);
    try {
      const summary = await api.get<RemovalSummary>(`/api/shelf/${work_id}/removal-summary`);
      if (summary.files === 0 && !summary.has_progress) {
        await api.delete(`/api/shelf/${work_id}?delete_files=false`);
        reload();
        return;
      }
      setRemoving({ summary, title });
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    }
  };

  const remove = async (summary: RemovalSummary, deleteFiles: boolean) => {
    setRemoving(null);
    setProblem(null);
    try {
      await api.delete(`/api/shelf/${summary.work_id}?delete_files=${deleteFiles}`);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      reload();
    }
  };

  return (
    <section className="screen">
      <h1 className="screen__title">{t("shelf.title")}</h1>

      <div className="toolbar">
        <div className="toolbar__tabs" role="tablist" aria-label={t("shelf.views")} onKeyDown={handleTabKeys}>
          {VIEWS.map((candidate) => (
            <button key={candidate.id} type="button" role="tab" className="chip"
                    id={`shelf-tab-${candidate.id}`} aria-controls="shelf-tabpanel"
                    aria-selected={activeView === candidate.id}
                    tabIndex={activeView === candidate.id ? 0 : -1}
                    onClick={() => { setView(candidate.id); setQuery(""); }}>
              {t(candidate.labelKey)}
            </button>
          ))}
        </div>
        <div className="toolbar__end">
          <input type="search" className="field" aria-label={t("shelf.search")} placeholder={t("shelf.search")}
                 value={query} onChange={(event) => setQuery(event.target.value)} />
          <select className="field" aria-label={t("shelf.sort")} value={sort}
                  onChange={(event) => setSort(event.target.value as typeof sort)}>
            <option value="added">{t("shelf.sort.added")}</option>
            <option value="title">{t("shelf.sort.title")}</option>
            <option value="last_read">{t("shelf.sort.lastRead")}</option>
            <option value="progress">{t("shelf.sort.progress")}</option>
            <option value="size">{t("shelf.sort.size")}</option>
          </select>
          <button type="button" className="iconbutton" aria-pressed={layout === "grid"}
                  onClick={() => setLayout("grid")} aria-label={t("shelf.layout.grid")}>
            <Icon name="grid" size={18} />
          </button>
          <button type="button" className="iconbutton" aria-pressed={layout === "list"}
                  onClick={() => setLayout("list")} aria-label={t("shelf.layout.list")}>
            <Icon name="list" size={18} />
          </button>
          <button type="button" className="chip" onClick={() => setTagsOpen(true)}>
            <Icon name="tag" size={14} /> {t("tags.title")}
          </button>
          {!selecting && entries.length > 0 && (
            <button type="button" className="chip" onClick={() => setSelecting(true)}>
              {t("shelf.batch.select")}
            </button>
          )}
        </div>
      </div>

      {selecting && (
        <div className="toolbar toolbar--batch" role="toolbar" aria-label={t("shelf.batch.actions")}>
          <span className="toolbar__count">{t("shelf.batch.selected", { count: selected.size })}</span>
          <button type="button" className="chip" onClick={selectAll}>{t("shelf.batch.selectAll")}</button>
          <button type="button" className="chip" disabled={batchBusy || selected.size === 0}
                  onClick={() => void batchAction("favorite")}>{t("shelf.batch.favorite")}</button>
          <button type="button" className="chip" disabled={batchBusy || selected.size === 0}
                  onClick={() => void batchAction("unfavorite")}>{t("shelf.batch.unfavorite")}</button>
          <button type="button" className="chip" disabled={batchBusy || selected.size === 0}
                  onClick={() => void batchAction("complete")}>{t("shelf.batch.complete")}</button>
          <button type="button" className="chip chip--danger" disabled={batchBusy || selected.size === 0}
                  onClick={() => void batchAction("remove")}>{t("shelf.batch.remove")}</button>
          <button type="button" className="chip" onClick={exitBatch}>{t("common.cancel")}</button>
        </div>
      )}

      {error !== null && <><p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button></>}
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {loading && <LoadingState />}

      <div role="tabpanel" id="shelf-tabpanel" aria-labelledby={`shelf-tab-${activeView}`} tabIndex={0}>
      <section ref={shelfRef} className="shelfview" role="region" aria-label={t("shelf.title")} data-layout={layout}>
        {entries.length === 0 && data !== null && !loading && <div className="empty shelfview__empty">
          <p className="empty__body">{t(searchTerm ? "shelf.searchEmpty" : "shelf.empty")}</p>
          {!searchTerm && activeView === "all" &&
            <Link className="button button--primary" to="/search">{t("home.empty.search")}</Link>}
        </div>}
        {layout === "list" ? (
          <div className="shelfview__list">
            {entries.map((entry) => (
              <div key={entry.work_id} className={`shelfview__row${selecting && selected.has(entry.work_id) ? " is-selected" : ""}`}>
                {selecting && (
                  <input type="checkbox" className="shelfview__check" checked={selected.has(entry.work_id)}
                         aria-label={t("shelf.batch.toggle", { title: entry.title })}
                         onChange={() => toggleSelect(entry.work_id)} />
                )}
                <WorkCard size="detailed" work={{ work_id: entry.work_id, title: entry.title, cover_url: entry.cover_url ?? null }} />
                {!selecting && <ManageButton entry={entry} onOpen={setManaging} />}
              </div>
            ))}
          </div>
        ) : (
          /* The shelf motif belongs here too (§32.9): works stand in rows on their own ledges. */
          chunk(entries, columns).map((row, rowIndex) => (
            <ShelfCase key={row[0]?.work_id ?? rowIndex} wrap>
              {row.map((entry) => (
                <div key={entry.work_id} className={`shelfview__selectable${selecting && selected.has(entry.work_id) ? " is-selected" : ""}`}
                     onClick={selecting ? () => toggleSelect(entry.work_id) : undefined}>
                  {selecting && (
                    <input type="checkbox" className="shelfview__check shelfview__check--grid" checked={selected.has(entry.work_id)}
                           aria-label={t("shelf.batch.toggle", { title: entry.title })}
                           onChange={() => toggleSelect(entry.work_id)} />
                  )}
                  <WorkCard work={{ work_id: entry.work_id, title: entry.title, cover_url: entry.cover_url ?? null }} />
                </div>
              ))}
            </ShelfCase>
          ))
        )}
      </section>
      </div>

      {managing !== null && (
        <ModalSurface className="confirm" title={t("shelf.manage.title", { title: managing.title })}
                      onClose={() => setManaging(null)}>
          <h2 className="display">{managing.title}</h2>
          <div className="confirm__actions">
            <button type="button" className="button" onClick={() => setManaging(null)}>{t("common.cancel")}</button>
            <button type="button" className="button"
                    onClick={() => void startRemoval(managing.work_id, managing.title)}>
              {t("shelf.remove.action")}
            </button>
          </div>
        </ModalSurface>
      )}

      {removing !== null && (
        <RemoveFromShelf title={removing.title} summary={removing.summary}
                         onKeep={() => void remove(removing.summary, false)}
                         onDelete={() => void remove(removing.summary, true)}
                         onCancel={() => setRemoving(null)} />
      )}

      {tagsOpen && <TagsDrawer onClose={() => setTagsOpen(false)} />}
    </section>
  );
}

/** A row's own actions live behind one control, so the shelf keeps looking like a shelf (§32.9). */
function ManageButton({ entry, onOpen }: {
  entry: { work_id: string; title: string };
  onOpen: (work: { work_id: string; title: string }) => void;
}) {
  const { t } = useI18n();
  return (
    <button type="button" className="chip shelfview__manage"
            onClick={() => onOpen({ work_id: entry.work_id, title: entry.title })}>
      {t("shelf.manage", { title: entry.title })}
    </button>
  );
}


function chunk<T>(items: T[], size: number): T[][] {
  const rows: T[][] = [];
  for (let index = 0; index < items.length; index += size) rows.push(items.slice(index, index + size));
  return rows;
}
