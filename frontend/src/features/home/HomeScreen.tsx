import { Link } from "react-router-dom";

import { useResource } from "@/api/useApi";
import type { HomeResponse } from "@/api/types";
import { HeroCarousel, type HeroSlide } from "@/components/HeroCarousel";
import { Shelf } from "@/components/Shelf";
import { WorkCard } from "@/components/WorkCard";
import { LoadingState } from "@/components/LoadingState";
import { ResultCard } from "@/features/search/ResultCard";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";

/**
 * Home (Master §31, §32.3–32.5).
 *
 * Every section is adaptive: it exists only when something real is behind it. Nothing here invents a
 * book, a statistic or a popularity score, and choosing the Hero costs no network request — the backend
 * picks it from Continue Reading, a pinned work, or already-cached discovery.
 */
export function HomeScreen() {
  const { t } = useI18n();
  const { data, error, reload } = useResource<HomeResponse>("/api/home");

  if (error !== null) {
    return (
      <section className="screen">
        <h1 className="screen__title">{t("home.welcome")}</h1>
        <p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button>
      </section>
    );
  }

  if (data === null) {
    return (
      <section className="screen">
        <h1 className="screen__title">{t("home.welcome")}</h1>
        <LoadingState />
      </section>
    );
  }

  const slides = buildHeroSlides(data, t);

  const hasAnything = slides.length > 0 || data.continue_reading.length > 0 || data.trending.length > 0
    || data.latest.length > 0 || data.recently_added.length > 0;

  return (
    <section className="screen">
      <h1 className="screen__title">{t("home.welcome")}</h1>
      <p className="screen__subtitle">{t("app.tagline")}</p>

      {slides.length > 0 && <HeroCarousel slides={slides} />}

      {data.continue_reading.length > 0 && (
        <Shelf id="continue" title={t("home.continue")} viewAllHref="/shelf">
          {data.continue_reading.map((item) => <WorkCard key={item.work_id} work={item} />)}
        </Shelf>
      )}

      {data.trending.length > 0 && (
        <Shelf id="trending" title={t("home.trending")} viewAllHref="/search" recessed>
          {data.trending.map((result) => <ResultCard key={result.work_id ?? result.title} result={result} />)}
        </Shelf>
      )}

      {(data.latest.length > 0 || data.recently_added.length > 0) && (
        <div className="home__sections">
          {data.latest.length > 0 && (
            <Shelf id="latest" title={t("home.latest")} viewAllHref="/search" compactRow>
              {data.latest.map((result) => (
                <ResultCard key={result.work_id ?? result.title} result={result} />
              ))}
            </Shelf>
          )}

          {data.recently_added.length > 0 && (
            <Shelf id="recent" title={t("home.recent")} viewAllHref="/shelf" compactRow>
              {data.recently_added.map((item) => <WorkCard key={item.work_id} work={item} />)}
            </Shelf>
          )}
        </div>
      )}

      {!hasAnything && <EmptyLibrary />}
    </section>
  );
}

function buildHeroSlides(data: HomeResponse, t: (key: StringKey) => string): HeroSlide[] {
  const slides: HeroSlide[] = [];
  const { hero } = data;
  if (hero) {
    const label = hero.reason === "continue_reading" ? t("home.continue")
      : hero.reason === "pinned" ? t("home.pinned") : t("home.discovery");
    slides.push({
      work_id: hero.work_id,
      title: hero.title,
      cover_url: hero.cover_url,
      description: hero.description,
      content_type: hero.content_type,
      label,
      fraction: data.continue_reading.find((cr) => cr.work_id === hero.work_id)?.fraction ?? null,
    });
  }
  for (const item of data.continue_reading) {
    if (slides.length >= 5) break;
    if (slides.some((s) => s.work_id === item.work_id)) continue;
    slides.push({
      work_id: item.work_id,
      title: item.title,
      cover_url: item.cover_url,
      content_type: item.content_type,
      label: t("home.continue"),
      fraction: item.fraction,
    });
  }
  return slides;
}

function EmptyLibrary() {
  const { t } = useI18n();
  return (
    <section className="empty home__empty">
      <h2 className="empty__title display">{t("home.empty.title")}</h2>
      <p className="empty__body">{t("home.empty.body")}</p>
      <div className="empty__actions">
        <Link className="button button--primary" to="/search">{t("home.empty.search")}</Link>
        <Link className="button" to="/settings/storage">{t("home.empty.import")}</Link>
      </div>
    </section>
  );
}
