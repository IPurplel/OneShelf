import { useState } from "react";

import { useResource } from "@/api/useApi";
import { Icon } from "@/components/Icon";
import type { ShelfResponse } from "@/api/types";
import { WorkCard } from "@/components/WorkCard";
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
  const { t } = useI18n();
  const [view, setView] = useState("all");
  const [query, setQuery] = useState("");
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const { data, error } = useResource<ShelfResponse>("/api/shelf",
    query.trim() ? { q: query.trim() } : { view });

  const entries = data?.entries ?? [];

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
              <WorkCard key={entry.work_id} size="detailed" work={{ work_id: entry.work_id, title: entry.title }} />
            ))}
          </div>
        ) : (
          /* The shelf motif belongs here too (§32.9): works stand in rows on their own planks. */
          chunk(entries, 6).map((row, index) => (
            <div className="shelf__case" key={row[0]?.work_id ?? index}>
              <div className="shelf__row shelf__row--wrap">
                {row.map((entry) => (
                  <WorkCard key={entry.work_id} work={{ work_id: entry.work_id, title: entry.title }} />
                ))}
              </div>
              <div className="shelf__plank" aria-hidden="true" />
            </div>
          ))
        )}
      </section>
    </section>
  );
}


function chunk<T>(items: T[], size: number): T[][] {
  const rows: T[][] = [];
  for (let index = 0; index < items.length; index += size) rows.push(items.slice(index, index + size));
  return rows;
}
