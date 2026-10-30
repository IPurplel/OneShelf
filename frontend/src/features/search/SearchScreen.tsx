import { useCallback, useEffect, useRef, useState } from "react";

import { Link, useSearchParams } from "react-router-dom";
import { motion } from "motion/react";

import { ApiError, api } from "@/api/client";
import type { SearchUpdate } from "@/api/types";
import { useResource } from "@/api/useApi";
import { ResultCard } from "./ResultCard";
import { Icon } from "@/components/Icon";
import { useI18n } from "@/i18n/i18n";
import { TRANSITION_EASE, useReducedMotion } from "@/lib/motion";
import { CATEGORIES, categoryLabel, languageLabel, parseScopes } from "./scopes";

type InstalledSource = { id: string; name: string; state: string; capabilities?: string[];
                         category?: string | null; languages?: string[] };
// Shown only until the installed sources are known (or if they cannot be read).
const FALLBACK_CATEGORIES = ["Manga", "Books", "Journal", "Academic books", "Children's books", "Manuscripts"];
const FALLBACK_LANGUAGES = ["AR"];

/**
 * The quick scopes offered are the categories and languages of the sources that can actually search,
 * in the catalogue's own order: a chip for a category nobody provides could only ever find nothing.
 */
function useQuickScopes(): { categories: string[]; languages: string[]; names: Map<string, string> } {
  const { data } = useResource<{ sources?: InstalledSource[] }>("/api/sources");
  const searchable = (Array.isArray(data?.sources) ? data.sources : [])
    .filter(source => source.state === "active" && (source.capabilities ?? []).includes("search"));
  const names = new Map((Array.isArray(data?.sources) ? data.sources : []).map(source => [source.id, source.name]));
  if (searchable.length === 0) return { categories: FALLBACK_CATEGORIES, languages: FALLBACK_LANGUAGES, names };
  const offered = new Set(searchable.map(source => source.category).filter((value): value is string => !!value));
  const categories = [...CATEGORIES.filter(value => offered.has(value)),
                      ...[...offered].filter(value => !(CATEGORIES as readonly string[]).includes(value))];
  const codes = new Set(searchable.flatMap(source => source.languages ?? []).map(code => code.toUpperCase())
    .filter(code => code !== "MULTI"));
  const languages = [...codes].sort((a, b) => a === "AR" ? -1 : b === "AR" ? 1 : a === "EN" ? -1 : b === "EN" ? 1
    : a.localeCompare(b)).slice(0, 4);
  return { categories, languages, names };
}

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
  const isLink = /^https?:\/\//i.test(submitted);
  const categories = params.getAll("category");
  const languages = params.getAll("language");
  const categoryKey = categories.join("\u0000");
  const languageKey = languages.join("\u0000");
  const [query, setQuery] = useState(submitted);
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [attempt, setAttempt] = useState(0);
  const [streamFailed, setStreamFailed] = useState(false);
  const [linkProblem, setLinkProblem] = useState<string | null>(null);
  useEffect(() => setQuery(submitted), [submitted]);
  const [update, setUpdate] = useState<SearchUpdate | null>(null);
  const [retryProblem, setRetryProblem] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const generation = useRef(0);
  const stream = useRef<EventSource | null>(null);
  const retainResults = useRef(false);
  const quick = useQuickScopes();
  const sourceName = (sourceId: string) => quick.names.get(sourceId) ?? sourceId.replace(/^oneshelf\./, "");

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
    setLinkProblem(null);
    setRetryProblem(null);
    setRetrying(null);
    if (submitted === "") return;
    if (isLink) {
      void api.post<{ result: SearchUpdate["results"][number] }>("/api/resolve-url", { url: submitted })
        .then(({ result }) => {
          if (generation.current !== current) return;
          setUpdate({ stage: "complete", results: [result], source_status: {},
            sources_total: 1, sources_done: 1, sources_failed: 0 });
        })
        .catch((error: unknown) => {
          if (generation.current !== current) return;
          setLinkProblem(error instanceof ApiError ? error.message : t("state.offline"));
        });
      return () => { generation.current++; };
    }
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
  }, [submitted, isLink, categoryKey, languageKey, attempt, close, t]);

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
          source: sourceName(sourceId), message: error instanceof ApiError ? error.message : t("state.offline"),
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
        {quick.categories.map(value =>
          <button type="button" className="chip" key={value} aria-pressed={categories.includes(value)}
            onClick={() => toggleScope("category", value)}>{categoryLabel(value, language)}</button>)}
        {quick.languages.map(code =>
          <button type="button" className="chip" key={`language:${code}`} aria-pressed={languages.includes(code)}
            onClick={() => toggleScope("language", code)}>{languageLabel(code, language)}</button>)}
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

      {submitted !== "" && update === null && !streamFailed && !linkProblem && <p role="status">{t("state.loading")}</p>}
      {(streamFailed || linkProblem) && (
        <div className="notice notice--problem">
          <p role="alert">{linkProblem ?? t("search.connectionFailed")}</p>
          <button className="button" type="button" onClick={() => { retainResults.current = true; setAttempt(value => value + 1); }}>
            {t("reader.retry")}
          </button>
        </div>
      )}

      {update !== null && !streamFailed && !isLink && update.sources_total > 0 && (
        <p className="search__status" role="status">
          {(categories.length > 0 || languages.length > 0) && <>{update.sources_available === undefined
            ? t("search.scopeActive", { count: update.sources_total })
            : t("search.scopeCount", { scoped: update.sources_total, available: update.sources_available })}. </>}
          {update.stage === "complete" && update.sources_failed > 0
            ? t(update.sources_failed === 1 ? "search.failed" : "search.failedMany", { count: update.sources_failed })
            : t("search.progress", { done: update.sources_done, total: update.sources_total })}
        </p>
      )}
      {update !== null && !streamFailed && !isLink && update.sources_total === 0 && (
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
              {t("search.retry", { source: sourceName(sourceId) })}
            </button>
          ))}
        </div>
      )}

      {retryProblem && <p className="notice notice--problem" role="alert">{retryProblem}</p>}

      {(update?.results.length ?? 0) > 0 && <div className="search__view" role="group" aria-label={t("search.layout")}>
        <button type="button" className="iconbutton" aria-pressed={layout === "grid"}
          aria-label={t("shelf.layout.grid")} onClick={() => setLayout("grid")}><Icon name="grid" size={18} /></button>
        <button type="button" className="iconbutton" aria-pressed={layout === "list"}
          aria-label={t("shelf.layout.list")} onClick={() => setLayout("list")}><Icon name="list" size={18} /></button>
      </div>}
      <SearchResults results={update?.results ?? []} layout={layout} />

      {update !== null && update.results.length === 0 && update.stage === "complete" && update.sources_total > 0 && (
        <p className="shelf__empty">{t("search.none")}</p>
      )}
    </section>
  );
}

function SearchResults({ results, layout }: { results: SearchUpdate["results"]; layout: "grid" | "list" }) {
  const reduced = useReducedMotion();
  return (
    <div className="search__results" data-layout={layout}>
      {results.map((result, i) => (
        <motion.div
          key={result.work_id ?? `${result.title}:${result.provenance[0]?.listing_key ?? ""}`}
          initial={reduced ? false : { opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...TRANSITION_EASE, delay: Math.min(i * 0.04, 0.3) }}
        >
          <ResultCard result={result} size={layout === "list" ? "detailed" : "standard"} />
        </motion.div>
      ))}
    </div>
  );
}
