import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/api/client";
import type { SearchUpdate } from "@/api/types";
import { ResultCard } from "./ResultCard";
import { useI18n } from "@/i18n/i18n";

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
  const [submitted, setSubmitted] = useState({ query: "" });
  const [update, setUpdate] = useState<SearchUpdate | null>(null);
  const [retryProblem, setRetryProblem] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const generation = useRef(0);
  const stream = useRef<EventSource | null>(null);

  const close = useCallback(() => {
    stream.current?.close();
    stream.current = null;
  }, []);

  useEffect(() => {
    const current = ++generation.current;
    close();
    setUpdate(null);
    setRetryProblem(null);
    setRetrying(null);
    if (submitted.query === "") return;
    const source = new EventSource(`/api/search?q=${encodeURIComponent(submitted.query)}`);
    stream.current = source;
    for (const stage of ["local", "partial", "complete"] as const) {
      source.addEventListener(stage, (event) => {
        if (generation.current !== current || stream.current !== source) return;
        setUpdate(JSON.parse((event as MessageEvent<string>).data) as SearchUpdate);
        if (stage === "complete") close();
      });
    }
    return () => { generation.current++; close(); };
  }, [submitted, close]);

  const retry = async (sourceId: string) => {
    const current = generation.current;
    setRetryProblem(null);
    setRetrying(sourceId);
    try {
      const result = await api.post<SearchUpdate>("/api/search/retry", { query: submitted.query, source_id: sourceId });
      if (current === generation.current) setUpdate(result);
    } catch (error) {
      if (current === generation.current) {
        setRetryProblem(t("search.retryFailed", {
          source: sourceId, message: error instanceof ApiError ? error.message : t("state.offline"),
        }));
      }
    } finally {
      if (current === generation.current) setRetrying(null);
    }
  };

  const failedSources = Object.entries(update?.source_status ?? {})
    .filter(([, status]) => status.state === "failed").map(([id]) => id);

  return (
    <section className="screen">
      <h1 className="screen__title">{t("search.title")}</h1>

      <form className="search__form" role="search" onSubmit={(event) => {
        event.preventDefault();
        generation.current++;
        close();
        setSubmitted({ query: query.trim() });
      }}>
        <input type="search" className="field field--large" aria-label={t("search.field")}
               placeholder={t("search.placeholder")} value={query}
               onChange={(event) => setQuery(event.target.value)} />
      </form>

      {submitted.query === "" && <p className="screen__subtitle">{t("search.intro")}</p>}

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
            <button key={sourceId} type="button" className="chip" disabled={retrying !== null}
                    aria-busy={retrying === sourceId || undefined} onClick={() => void retry(sourceId)}>
              {t("search.retry", { source: sourceId })}
            </button>
          ))}
        </div>
      )}

      {retryProblem && <p className="notice notice--problem" role="alert">{retryProblem}</p>}

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
