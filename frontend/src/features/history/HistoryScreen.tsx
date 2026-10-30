import { useMemo } from "react";
import { Link } from "react-router-dom";

import { useResource } from "@/api/useApi";
import { LoadingState } from "@/components/LoadingState";
import { WorkCard } from "@/components/WorkCard";
import { useI18n } from "@/i18n/i18n";

type HistoryEntry = {
  updated_at: string;
  read_state: string;
  fraction: number | null;
  unit_title: string | null;
  work_id: string;
  work_title: string;
  cover_url: string | null;
};

type HistoryResponse = { entries: HistoryEntry[] };

type DayGroup = { label: string; date: string; entries: HistoryEntry[] };

/** The reader's own calendar day (stored times are UTC, and a day boundary is local). */
function localDay(value: Date): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function dayLabel(dateStr: string, today: string, yesterday: string, t: ReturnType<typeof useI18n>["t"],
                  language: string): string {
  if (dateStr === today) return t("history.today");
  if (dateStr === yesterday) return t("history.yesterday");
  const [year, month, day] = dateStr.split("-").map(Number);
  return new Intl.DateTimeFormat(language, { dateStyle: "full" }).format(new Date(year!, month! - 1, day!));
}

export function HistoryScreen() {
  const { t, language } = useI18n();
  const { data, error, loading } = useResource<HistoryResponse>("/api/history");

  const today = localDay(new Date());
  const yesterdayDate = localDay(new Date(Date.now() - 86_400_000));
  const time = new Intl.DateTimeFormat(language, { timeStyle: "short" });

  const groups: DayGroup[] = useMemo(() => {
    if (!data) return [];
    const map = new Map<string, HistoryEntry[]>();
    for (const entry of data.entries) {
      const date = localDay(new Date(entry.updated_at));
      const group = map.get(date);
      if (group) group.push(entry);
      else map.set(date, [entry]);
    }
    return [...map.entries()].map(([date, entries]) => ({
      label: dayLabel(date, today, yesterdayDate, t, language),
      date,
      entries,
    }));
  }, [data, today, yesterdayDate, t, language]);

  return (
    <section className="screen">
      <h1 className="screen__title">{t("history.title")}</h1>
      <p className="screen__subtitle">{t("history.subtitle")}</p>

      {error !== null && <p className="notice notice--problem" role="alert">{error}</p>}
      {loading && <LoadingState />}

      {data && groups.length === 0 && (
        <div className="empty">
          <p className="empty__body">{t("history.empty")}</p>
        </div>
      )}

      {groups.map((group) => (
        <section key={group.date} className="history__day">
          <h2 className="history__dayLabel display">{group.label}</h2>
          <ul className="history__list">
            {group.entries.map((entry, i) => (
              <li key={`${entry.work_id}-${entry.updated_at}-${i}`} className="history__item">
                <Link to={`/works/${entry.work_id}`} className="history__link">
                  {/* No work id here: the row is already the link, and a link inside a link is invalid. */}
                  <WorkCard size="compact" work={{ work_id: null, title: entry.work_title, cover_url: entry.cover_url }} />
                  <div className="history__info">
                    <span className="history__workTitle" dir="auto">{entry.work_title}</span>
                    {entry.unit_title && <span className="history__unitTitle" dir="auto">{entry.unit_title}</span>}
                    <time className="history__time" dateTime={entry.updated_at}>
                      {time.format(new Date(entry.updated_at))}
                    </time>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </section>
  );
}
