import { Link } from "react-router-dom";

import { useResource } from "@/api/useApi";
import type { HomeResponse } from "@/api/types";
import { Shelf } from "@/components/Shelf";
import { WorkCard } from "@/components/WorkCard";
import { useI18n } from "@/i18n/i18n";

/**
 * Home (Master §31, §32.3–32.5).
 *
 * Every section is adaptive: it exists only when something real is behind it. Nothing here invents a
 * book, a statistic or a popularity score, and choosing the Hero costs no network request — the backend
 * picks it from Continue Reading, a pinned work, or already-cached discovery.
 */
export function HomeScreen() {
  const { t } = useI18n();
  const { data, error } = useResource<HomeResponse>("/api/home");

  if (error !== null) {
    return (
      <section className="screen">
        <h1 className="screen__title">{t("home.welcome")}</h1>
        <p className="notice notice--problem" role="alert">{t("state.offline")}</p>
      </section>
    );
  }

  if (data === null) {
    return (
      <section className="screen">
        <h1 className="screen__title">{t("home.welcome")}</h1>
        <p className="screen__subtitle">{t("state.loading")}</p>
      </section>
    );
  }

  const hasAnything = Boolean(data.hero) || data.continue_reading.length > 0 || data.trending.length > 0
    || data.latest.length > 0 || data.recently_added.length > 0;

  return (
    <section className="screen">
      <h1 className="screen__title">{t("home.welcome")}</h1>
      <p className="screen__subtitle">{t("app.tagline")}</p>

      {data.hero && <Hero hero={data.hero} fraction={data.continue_reading[0]?.fraction ?? null} />}

      {data.continue_reading.length > 0 && (
        <Shelf id="continue" title={t("home.continue")} viewAllHref="/shelf">
          {data.continue_reading.map((item) => <WorkCard key={item.work_id} work={item} />)}
        </Shelf>
      )}

      {data.trending.length > 0 && (
        <Shelf id="trending" title={t("home.trending")} viewAllHref="/search" recessed>
          {data.trending.map((result) => <WorkCard key={result.work_id ?? result.title} work={result} />)}
        </Shelf>
      )}

      {(data.latest.length > 0 || data.recently_added.length > 0) && (
        <div className="home__pair">
          {data.latest.length > 0 && (
            <Shelf id="latest" title={t("home.latest")} viewAllHref="/search" compactRow>
              {data.latest.map((result) => (
                <WorkCard key={result.work_id ?? result.title} work={result} size="compact" />
              ))}
            </Shelf>
          )}

          {data.recently_added.length > 0 && (
            <Shelf id="recent" title={t("home.recent")} viewAllHref="/shelf" compactRow>
              {data.recently_added.map((item) => <WorkCard key={item.work_id} work={item} size="compact" />)}
            </Shelf>
          )}
        </div>
      )}

      {!hasAnything && <EmptyLibrary />}
    </section>
  );
}

function Hero({ hero, fraction }: { hero: NonNullable<HomeResponse["hero"]>; fraction: number | null }) {
  const { t } = useI18n();
  const label = hero.reason === "continue_reading" ? t("home.continue")
    : hero.reason === "pinned" ? t("home.pinned") : t("home.discovery");
  const percent = fraction === null ? null : Math.round(fraction * 100);

  return (
    <section className="hero" role="region" aria-label={hero.title}>
      {hero.cover_url && <img className="hero__art" src={hero.cover_url} alt="" />}
      <div className="hero__inner">
        <span className="hero__cover" aria-hidden="true">
          {hero.cover_url ? <img src={hero.cover_url} alt="" /> : <span className="hero__blank" />}
        </span>
        <div className="hero__body">
          <p className="hero__reason">{label}</p>
          <h2 className="hero__title display">{hero.title}</h2>
          {hero.description && <p className="hero__description">{hero.description}</p>}
          {percent !== null && <p className="hero__progress">{`${percent}%`}</p>}
          {hero.work_id && (
            <Link className="button button--primary hero__action" to={`/works/${hero.work_id}`}>
              <span className="hero__play" aria-hidden="true">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor"><path d="M3 1.5 10 6l-7 4.5z" /></svg>
              </span>
              {label}
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}

function EmptyLibrary() {
  const { t } = useI18n();
  return (
    <section className="empty">
      <h2 className="empty__title display">{t("home.empty.title")}</h2>
      <p className="empty__body">{t("home.empty.body")}</p>
      <div className="empty__actions">
        <Link className="button button--primary" to="/search">{t("home.empty.search")}</Link>
        <Link className="button" to="/settings/storage">{t("home.empty.import")}</Link>
      </div>
    </section>
  );
}
