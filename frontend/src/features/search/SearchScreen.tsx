import { useCallback, useEffect, useRef, useState } from "react";

import { Link, useSearchParams } from "react-router-dom";

import { ApiError, api } from "@/api/client";
import type { SearchUpdate } from "@/api/types";
import { ResultCard } from "./ResultCard";
import { useI18n } from "@/i18n/i18n";
import { categoryLabel, languageLabel, parseScopes } from "./scopes";

/**
 * Search (Master §6, §32.7).
 *
 * The library answers first and its results stay on screen while sources catch up. A source that fails
 * is named with a way to retry it — results are never hidden because one source is unhappy, and there is
 * no invented relevance score to show.
 */
export function SearchScreen() {
  const { t, language } = useI18n();
  const [params, setParams] = useSearchParams();
  const submitted = (params.get("q") ?? "").trim();
  const categories = params.getAll("category");
  const languages = params.getAll("language");
  const categoryKey = categories.join("\u0000");
  const languageKey = languages.join("\u0000");
  const [query, setQuery] = useState(submitted);
  const [attempt, setAttempt] = useState(0);
  const [streamFailed, setStreamFailed] = useState(false);
  useEffect(() => setQuery(submitted), [submitted]);
  const [update, setUpdate] = useState<SearchUpdate | null>(null);
  const [retryProblem, setRetryProblem] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const generation = useRef(0);
  const stream = useRef<EventSource | null>(null);
  const retainResults = useRef(false);

  const close = useCallback(() => {
    stream.current?.close();
    stream.current = null;
  }, []);

  useEffect(() => {
    const current = ++generation.current;
    close();
    if (!retainResults.current) setUpdate(null);
    retainResults.current = false;
    setStreamFailed(false);
    setRetryProblem(null);
    setRetrying(null);
    if (submitted === "") return;
    const searchParams = new URLSearchParams({ q: submitted });
    for (const category of categories) searchParams.append("category", category);
    for (const language of languages) searchParams.append("language", language);
    const source = new EventSource(`/api/search?${searchParams.toString()}`);
    stream.current = source;
    source.addEventListener("error", () => {
      if (generation.current !== current || stream.current !== source) return;
      setStreamFailed(true);
      close();
    });
    for (const stage of ["local", "partial", "complete"] as const) {
      source.addEventListener(stage, (event) => {
        if (generation.current !== current || stream.current !== source) return;
        setUpdate(JSON.parse((event as MessageEvent<string>).data) as SearchUpdate);
        if (stage === "complete") close();
      });
    }
    return () => { generation.current++; close(); };
  // Keys change only when scope values change; URLSearchParams is a new object on render.
  }, [submitted, categoryKey, languageKey, attempt, close]);

  const removeScope = (kind: "category" | "language", value: string) => {
    const next = new URLSearchParams(params);
    next.delete(kind);
    for (const scope of (kind === "category" ? categories : languages).filter(scope => scope !== value)) next.append(kind, scope);
    setParams(next);
  };

  const toggleScope = (kind: "category" | "language", value: string) => {
    const next = new URLSearchParams(params);
    const scopes = kind === "category" ? categories : languages;
    next.delete(kind);
    for (const scope of scopes.filter(scope => scope !== value)) next.append(kind, scope);
    if (!scopes.includes(value)) next.append(kind, value);
    setParams(next);
  };

  const retry = async (sourceId: string) => {
    const current = generation.current;
    setRetryProblem(null);
    setRetrying(sourceId);
    try {
      const result = await api.post<SearchUpdate>("/api/search/retry", {
        query: submitted, source_id: sourceId, categories, languages,
      });
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
        const parsed = parseScopes(query);
        setQuery(parsed.query);
        const next = new URLSearchParams();
        if (parsed.query) next.set("q", parsed.query);
        for (const category of Array.from(new Set([...categories, ...parsed.categories]))) next.append("category", category);
        for (const language of Array.from(new Set([...languages, ...parsed.languages]))) next.append("language", language);
        if (next.toString() === params.toString()) setAttempt(value => value + 1);
        else setParams(next);
      }}>
        <input type="search" className="field field--large" aria-label={t("search.field")}
               placeholder={t("search.placeholder")} value={query}
               onChange={(event) => setQuery(event.target.value)} />
      </form>

      <p className="search__scope-hint">{t("search.scopeHint")}</p>
      <div className="search__quick-scopes" role="group" aria-label={t("search.quickScopes")}>
        {(["Manga", "Books", "Journal", "Academic books", "Children's books", "Manuscripts"] as const).map(value =>
          <button type="button" className="chip" key={value} aria-pressed={categories.includes(value)}
            onClick={() => toggleScope("category", value)}>{categoryLabel(value, language)}</button>)}
        <button type="button" className="chip" aria-pressed={languages.includes("AR")}
          onClick={() => toggleScope("language", "AR")}>{languageLabel("AR", language)}</button>
      </div>
      {(categories.length > 0 || languages.length > 0) && <div className="search__scopes" role="group" aria-label={t("search.scopes")}>
        {categories.map(category => <button type="button" className="chip" key={`category:${category}`}
          onClick={() => removeScope("category", category)}>
          {t("search.scopeRemove", { scope: categoryLabel(category, language) })}
        </button>)}
        {languages.map(code => <button type="button" className="chip" key={`language:${code}`}
          onClick={() => removeScope("language", code)}>
          {t("search.scopeRemove", { scope: languageLabel(code, language) })}
        </button>)}
      </div>}

      {submitted === "" && <p className="screen__subtitle">{t("search.intro")}</p>}

      {submitted !== "" && update === null && !streamFailed && <p role="status">{t("state.loading")}</p>}
      {streamFailed && (
        <div className="notice notice--problem">
          <p role="alert">{t("search.connectionFailed")}</p>
          <button className="button" type="button" onClick={() => { retainResults.current = true; setAttempt(value => value + 1); }}>
            {t("reader.retry")}
          </button>
        </div>
      )}

      {update !== null && !streamFailed && update.sources_total > 0 && (
        <p className="search__status" role="status">
          {(categories.length > 0 || languages.length > 0) && <>{update.sources_available === undefined
            ? t("search.scopeActive", { count: update.sources_total })
            : t("search.scopeCount", { scoped: update.sources_total, available: update.sources_available })}. </>}
          {update.stage === "complete" && update.sources_failed > 0
            ? t(update.sources_failed === 1 ? "search.failed" : "search.failedMany", { count: update.sources_failed })
            : t("search.progress", { done: update.sources_done, total: update.sources_total })}
        </p>
      )}
      {update !== null && !streamFailed && update.sources_total === 0 && (
        <p className="search__status" role="status">{update.sources_available !== undefined && update.sources_available > 0
          && (categories.length > 0 || languages.length > 0)
          ? t("search.noScopeSources")
          : <>{t("search.noSources")} <Link to="/sources">{t("search.addSource")}</Link></>}</p>
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

      {update !== null && update.results.length === 0 && update.stage === "complete" && update.sources_total > 0 && (
        <p className="shelf__empty">{t("search.none")}</p>
      )}
    </section>
  );
}
