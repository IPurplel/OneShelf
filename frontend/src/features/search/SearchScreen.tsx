import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import type { ResultWork } from "@/api/types";
import { ResultCard } from "./ResultCard";
import { useI18n } from "@/i18n/i18n";

type Update = {
  stage: "local" | "partial" | "complete";
  results: ResultWork[];
  source_status: Record<string, string>;
  sources_total: number;
  sources_done: number;
  sources_failed: number;
};

/**
 * Search (Master §6, §32.7).
 *
 * The library answers first and its results stay on screen while sources catch up. A source that fails
 * is named with a way to retry it — results are never hidden because one source is unhappy, and there is
 * no invented relevance score to show.
 */
export function SearchScreen() {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [update, setUpdate] = useState<Update | null>(null);
  const stream = useRef<EventSource | null>(null);

  const close = useCallback(() => {
    stream.current?.close();
    stream.current = null;
  }, []);

  useEffect(() => {
    if (submitted === "") return;
    close();
    setUpdate(null);
    const source = new EventSource(`/api/search?q=${encodeURIComponent(submitted)}`);
    stream.current = source;
    for (const stage of ["local", "partial", "complete"] as const) {
      source.addEventListener(stage, (event) => {
        setUpdate(JSON.parse((event as MessageEvent<string>).data) as Update);
        if (stage === "complete") close();
      });
    }
    return close;
  }, [submitted, close]);

  const retry = async (sourceId: string) => {
    const result = await api.post<Update>("/api/search/retry", { query: submitted, source_id: sourceId });
    setUpdate(result);
  };

  const failedSources = Object.entries(update?.source_status ?? {})
    .filter(([, status]) => status !== "ok").map(([id]) => id);

  return (
    <section className="screen">
      <h1 className="screen__title">{t("search.title")}</h1>

      <form className="search__form" role="search" onSubmit={(event) => { event.preventDefault(); setSubmitted(query.trim()); }}>
        <input type="search" className="field field--large" aria-label={t("search.field")}
               placeholder={t("search.placeholder")} value={query}
               onChange={(event) => setQuery(event.target.value)} />
      </form>

      {submitted === "" && <p className="screen__subtitle">{t("search.intro")}</p>}

      {update !== null && (
        <p className="search__status" role="status">
          {update.stage === "complete" && update.sources_failed > 0
            ? t(update.sources_failed === 1 ? "search.failed" : "search.failedMany", { count: update.sources_failed })
            : t("search.progress", { done: update.sources_done, total: update.sources_total })}
        </p>
      )}

      {failedSources.length > 0 && (
        <div className="search__retries">
          {failedSources.map((sourceId) => (
            <button key={sourceId} type="button" className="chip" onClick={() => void retry(sourceId)}>
              {t("search.retry", { source: sourceId })}
            </button>
          ))}
        </div>
      )}

      <div className="search__results">
        {(update?.results ?? []).map((result) => (
          <ResultCard key={result.work_id ?? `${result.title}:${result.provenance[0]?.listing_key ?? ""}`} result={result} />
        ))}
      </div>

      {update !== null && update.results.length === 0 && update.stage === "complete" && (
        <p className="shelf__empty">{t("search.none")}</p>
      )}
    </section>
  );
}
