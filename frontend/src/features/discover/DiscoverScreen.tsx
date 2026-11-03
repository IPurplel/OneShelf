import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "@/api/client";
import type { ResultWork, ShelfEntry } from "@/api/types";
import { useResource } from "@/api/useApi";
import { Icon } from "@/components/Icon";
import { LoadingState } from "@/components/LoadingState";
import { WorkCard } from "@/components/WorkCard";
import { ResultCard } from "@/features/search/ResultCard";
import { useI18n } from "@/i18n/i18n";

type Feed = "latest" | "trending";
type DiscoverSource = { source_id: string; name: string; feeds: Feed[]; category: string | null; languages: string[] };
type DiscoverItem = ResultWork & { on_shelf: boolean };
type FeedPage = { source_id: string; kind: Feed; page: number; has_more: boolean; cached: boolean; items: DiscoverItem[] };
type SourcePick = { item: DiscoverItem | null; reason: { source_id: string; source_name: string; kind: Feed } | null };
type ShelfPick = { item: ShelfEntry | null; reason: { kind: "not_started" } | null };

/**
 * Discover (docs/adr/0004-discover.md): find something to read without knowing its name.
 *
 * Two surprises — something new from a source's own lists, or something on the shelf not started yet — and
 * each source's Latest and Popular lists, read one page at a time. The order is always the source's own;
 * OneShelf ranks nothing here and says where every suggestion came from.
 */
export function DiscoverScreen() {
  const { t } = useI18n();
  const { data, error, loading, reload } = useResource<{ sources: DiscoverSource[] }>("/api/discover/sources");
  const sources = data?.sources ?? [];

  return (
    <section className="screen discover">
      <h1 className="screen__title">{t("discover.title")}</h1>
      <p className="screen__subtitle">{t("discover.subtitle")}</p>

      <div className="discover__surprises">
        <SourcesSurprise disabled={data !== null && sources.length === 0} />
        <ShelfSurprise />
      </div>

      {error !== null && <><p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button></>}
      {loading && data === null && <LoadingState variant="shelf" />}
      {data !== null && sources.length === 0 && (
        <div className="empty">
          <p className="empty__body">{t("discover.noSources")}</p>
          <Link className="button" to="/sources">{t("nav.sources")}</Link>
        </div>
      )}
      {sources.length > 0 && <SourceBrowser sources={sources} />}
    </section>
  );
}

function SourcesSurprise({ disabled }: { disabled: boolean }) {
  const { t, errorText } = useI18n();
  const [pick, setPick] = useState<SourcePick | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const draw = async () => {
    setBusy(true);
    setProblem(null);
    try {
      setPick(await api.get<SourcePick>("/api/discover/random", { from: "sources" }));
    } catch (error) {
      setProblem(errorText(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Surprise icon="discover" title={t("discover.surprise.sources.title")} body={t("discover.surprise.sources.body")}
              busy={busy} disabled={disabled} drawn={pick !== null} onDraw={() => void draw()} problem={problem}
              empty={pick !== null && pick.item === null ? t("discover.none.sources") : null}>
      {pick?.item && pick.reason && (
        <>
          <ResultCard result={pick.item} />
          <p className="discover__reason">
            {t("discover.reason.sources", { source: pick.reason.source_name,
                                             list: t(`discover.feed.${pick.reason.kind}`) })}
          </p>
        </>
      )}
    </Surprise>
  );
}

function ShelfSurprise() {
  const { t, errorText } = useI18n();
  const [pick, setPick] = useState<ShelfPick | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const draw = async () => {
    setBusy(true);
    setProblem(null);
    try {
      setPick(await api.get<ShelfPick>("/api/discover/random", { from: "library" }));
    } catch (error) {
      setProblem(errorText(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Surprise icon="shelf" title={t("discover.surprise.library.title")} body={t("discover.surprise.library.body")}
              busy={busy} drawn={pick !== null} onDraw={() => void draw()} problem={problem}
              empty={pick !== null && pick.item === null ? t("discover.none.library") : null}>
      {pick?.item && (
        <>
          <WorkCard work={{ work_id: pick.item.work_id, title: pick.item.title, cover_url: pick.item.cover_url ?? null,
                            content_type: pick.item.content_type ?? null,
                            downloaded: (pick.item.downloaded_units ?? 0) > 0 }} />
          <p className="discover__reason">{t("discover.reason.library")}</p>
        </>
      )}
    </Surprise>
  );
}

/** One surprise: what it offers, a button, and — once drawn — the work, why it was chosen, and "Another". */
function Surprise({ icon, title, body, busy, disabled = false, drawn, onDraw, problem, empty, children }: {
  icon: string; title: string; body: string; busy: boolean; disabled?: boolean; drawn: boolean;
  onDraw: () => void; problem: string | null; empty: string | null; children: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <section className="discover__surprise" aria-busy={busy || undefined}>
      <div className="discover__surpriseHead">
        <span className="discover__surpriseIcon" aria-hidden="true"><Icon name={icon} size={22} /></span>
        <div>
          <h2 className="display">{title}</h2>
          <p>{body}</p>
        </div>
      </div>
      {drawn && <div className="discover__pick" aria-live="polite">{children}{empty && <p className="discover__reason">{empty}</p>}</div>}
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      <button type="button" className={`button${drawn ? "" : " button--primary"}`} disabled={busy || disabled}
              onClick={onDraw}>
        {drawn ? t("discover.another") : t("discover.pick")}
      </button>
    </section>
  );
}

function SourceBrowser({ sources }: { sources: DiscoverSource[] }) {
  const { t, errorText } = useI18n();
  // Which source and list are in the address, so a choice survives a reload and can be shared.
  const [params, setParams] = useSearchParams();
  const source = sources.find((s) => s.source_id === params.get("source")) ?? sources[0]!;
  const kind: Feed = source.feeds.includes(params.get("kind") as Feed) ? params.get("kind") as Feed : source.feeds[0]!;
  const choose = (next: { source?: string; kind?: Feed }) => {
    const chosen = sources.find((s) => s.source_id === (next.source ?? source.source_id))!;
    const feed = next.kind && chosen.feeds.includes(next.kind) ? next.kind : chosen.feeds[0]!;
    setParams({ source: chosen.source_id, kind: feed }, { replace: true });
  };

  const [items, setItems] = useState<DiscoverItem[]>([]);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const generation = useRef(0);

  const load = useCallback(async (next: number, reset: boolean) => {
    const mine = ++generation.current;
    setBusy(true);
    setProblem(null);
    if (reset) setItems([]);
    try {
      const found = await api.get<FeedPage>("/api/discover/list", { source: source.source_id, kind, page: next });
      if (mine !== generation.current) return;          // the reader moved on to another source or list
      setItems((current) => {
        const seen = new Set((reset ? [] : current).map(keyOf));
        return [...(reset ? [] : current), ...found.items.filter((item) => !seen.has(keyOf(item)))];
      });
      setPage(next);
      setHasMore(found.has_more);
    } catch (error) {
      if (mine === generation.current) setProblem(errorText(error));
    } finally {
      if (mine === generation.current) setBusy(false);
    }
  }, [source.source_id, kind, errorText]);

  useEffect(() => { void load(1, true); }, [load]);

  return (
    <section className="discover__browser" aria-labelledby="discover-browse-title">
      <h2 className="discover__heading display" id="discover-browse-title">{t("discover.browse")}</h2>
      <div className="discover__sources" role="group" aria-label={t("discover.sources.label")}>
        {sources.map((candidate) => (
          <button key={candidate.source_id} type="button" className="chip"
                  aria-pressed={candidate.source_id === source.source_id}
                  onClick={() => choose({ source: candidate.source_id })}>
            <bdi>{candidate.name}</bdi>
          </button>
        ))}
      </div>
      {source.feeds.length > 1 && (
        <div className="discover__feeds" role="group" aria-label={t("discover.feed.label")}>
          {source.feeds.map((feed) => (
            <button key={feed} type="button" className="chip" aria-pressed={feed === kind}
                    onClick={() => choose({ kind: feed })}>
              {t(`discover.feed.${feed}`)}
            </button>
          ))}
        </div>
      )}

      {busy && items.length === 0 && <LoadingState variant="shelf" />}
      {items.length > 0 && (
        <ul className="search__results discover__results" aria-label={`${source.name} · ${t(`discover.feed.${kind}`)}`}>
          {items.map((item) => (
            <li key={keyOf(item)} className="discover__item">
              <ResultCard result={item} />
              {item.on_shelf && <span className="discover__onShelf">{t("discover.onShelf")}</span>}
            </li>
          ))}
        </ul>
      )}
      {problem !== null && <>
        <p className="notice notice--problem" role="alert">{problem}</p>
        <button type="button" className="button" onClick={() => void load(page + 1 || 1, page === 0)}>{t("reader.retry")}</button>
      </>}
      {!busy && problem === null && items.length === 0 && <p className="discover__end">{t("discover.empty")}</p>}
      <div className="discover__more">
        {items.length > 0 && hasMore && (
          <button type="button" className="button" disabled={busy} aria-busy={busy || undefined}
                  onClick={() => void load(page + 1, false)}>
            {t("discover.loadMore")}
          </button>
        )}
        {items.length > 0 && !hasMore && <p className="discover__end">{t("discover.end")}</p>}
      </div>
    </section>
  );
}

function keyOf(item: DiscoverItem): string {
  const first = item.provenance[0];
  return item.work_id ?? (first ? `${first.source_id}:${first.listing_key}` : item.title);
}
