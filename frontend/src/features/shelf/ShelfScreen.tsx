import { useMemo, useState } from "react";

import { useResource } from "@/api/useApi";
import { Icon } from "@/components/Icon";
import type { ShelfResponse } from "@/api/types";
import { WorkCard } from "@/components/WorkCard";
import { RemoveFromShelf } from "./RemoveFromShelf";
import type { RemovalSummary } from "./RemoveFromShelf";
import { api } from "@/api/client";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";

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
  const [view, setView] = useState("all");
  const [query, setQuery] = useState("");
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [sort, setSort] = useState<"added" | "title">("added");
  const [managing, setManaging] = useState<{ work_id: string; title: string } | null>(null);
  const [removing, setRemoving] = useState<{ summary: RemovalSummary; title: string } | null>(null);
  const { data, error, reload } = useResource<ShelfResponse>("/api/shelf",
    query.trim() ? { q: query.trim() } : { view });

  /**
   * §32.9: sorting is the screen's own work. The shelf arrives whole and local, so reordering it needs
   * no second request — and "added" is the order the library already gave, left exactly as it came.
   */
  const entries = useMemo(() => {
    const rows = data?.entries ?? [];
    if (sort !== "title") return rows;
    return [...rows].sort((a, b) => a.title.localeCompare(b.title, language));
  }, [data, sort, language]);

  /** The same removal a work's own page offers, from a row, with the same facts and the same words. */
  const startRemoval = async (work_id: string, title: string) => {
    setManaging(null);
    try {
      const summary = await api.get<RemovalSummary>(`/api/shelf/${work_id}/removal-summary`);
      if (summary.files === 0 && !summary.has_progress) {
        await api.delete(`/api/shelf/${work_id}?delete_files=false`);
        reload();
        return;
      }
      setRemoving({ summary, title });
    } catch {
      // A library that cannot be reached removes nothing; the row stays as it is.
    }
  };

  const remove = async (summary: RemovalSummary, deleteFiles: boolean) => {
    setRemoving(null);
    try {
      await api.delete(`/api/shelf/${summary.work_id}?delete_files=${deleteFiles}`);
    } finally {
      reload();
    }
  };

  return (
    <section className="screen">
      <h1 className="screen__title">{t("shelf.title")}</h1>

      <div className="toolbar">
        <div className="toolbar__tabs" role="tablist" aria-label={t("shelf.views")}>
          {VIEWS.map((candidate) => (
            <button key={candidate.id} type="button" role="tab" className="chip"
                    aria-selected={view === candidate.id && query.trim() === ""}
                    onClick={() => { setView(candidate.id); setQuery(""); }}>
              {t(candidate.labelKey)}
            </button>
          ))}
        </div>
        <div className="toolbar__end">
          <input type="search" className="field" aria-label={t("shelf.search")} placeholder={t("shelf.search")}
                 value={query} onChange={(event) => setQuery(event.target.value)} />
          <select className="field" aria-label={t("shelf.sort")} value={sort}
                  onChange={(event) => setSort(event.target.value as "added" | "title")}>
            <option value="added">{t("shelf.sort.added")}</option>
            <option value="title">{t("shelf.sort.title")}</option>
          </select>
          <button type="button" className="iconbutton" aria-pressed={layout === "grid"}
                  onClick={() => setLayout("grid")} aria-label={t("shelf.layout.grid")}>
            <Icon name="grid" size={18} />
          </button>
          <button type="button" className="iconbutton" aria-pressed={layout === "list"}
                  onClick={() => setLayout("list")} aria-label={t("shelf.layout.list")}>
            <Icon name="list" size={18} />
          </button>
        </div>
      </div>

      {error !== null && <p className="notice notice--problem" role="alert">{t("state.offline")}</p>}

      <section className="shelfview" role="region" aria-label={t("shelf.title")} data-layout={layout}>
        {entries.length === 0 && data !== null && <p className="shelf__empty">{t("shelf.empty")}</p>}
        {layout === "list" ? (
          <div className="shelfview__list">
            {entries.map((entry) => (
              <div key={entry.work_id} className="shelfview__row">
                <WorkCard size="detailed" work={{ work_id: entry.work_id, title: entry.title, cover_url: entry.cover_url ?? null }} />
                <ManageButton entry={entry} onOpen={setManaging} />
              </div>
            ))}
          </div>
        ) : (
          /* The shelf motif belongs here too (§32.9): works stand in rows on their own planks. */
          chunk(entries, 6).map((row, index) => (
            <div className="shelf__case" key={row[0]?.work_id ?? index}>
              <div className="shelf__row shelf__row--wrap">
                {row.map((entry) => (
                  <WorkCard key={entry.work_id} work={{ work_id: entry.work_id, title: entry.title, cover_url: entry.cover_url ?? null }} />
                ))}
              </div>
              <div className="shelf__plank" aria-hidden="true" />
            </div>
          ))
        )}
      </section>

      {managing !== null && (
        <div className="confirm" role="dialog" aria-modal="true"
             aria-label={t("shelf.manage.title", { title: managing.title })}>
          <h2 className="display">{managing.title}</h2>
          <div className="confirm__actions">
            <button type="button" className="button" onClick={() => setManaging(null)}>{t("common.cancel")}</button>
            <button type="button" className="button"
                    onClick={() => void startRemoval(managing.work_id, managing.title)}>
              {t("shelf.remove.action")}
            </button>
          </div>
        </div>
      )}

      {removing !== null && (
        <RemoveFromShelf title={removing.title} summary={removing.summary}
                         onKeep={() => void remove(removing.summary, false)}
                         onDelete={() => void remove(removing.summary, true)}
                         onCancel={() => setRemoving(null)} />
      )}
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
