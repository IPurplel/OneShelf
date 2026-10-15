import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { languageName } from "@/i18n/language";
import { useI18n } from "@/i18n/i18n";
import { CoverPlaceholder } from "@/components/CoverPlaceholder";

export type CardWork = {
  work_id: string | null;
  title: string;
  cover_url?: string | null;
  content_type?: string | null;
  fraction?: number | null;
  availability?: Record<string, number>;
};

/**
 * One logical Work, in three sizes (Master §32.6, and the approved reference).
 *
 * The cover stays dominant and stands on the shelf; below the front edge come the title, the kind of work,
 * and — when there is progress — a slim olive bar with its percentage. Availability stays concise: a
 * language and a source count, never every internal state.
 */
export function WorkCard({ work, size = "standard", onOpen, busy = false, problem }: {
  work: CardWork;
  size?: "compact" | "standard" | "detailed";
  /** For a result with no Work yet: the card is a button that opens it (see ResultCard). */
  onOpen?: () => void;
  busy?: boolean;
  problem?: string | null;
}) {
  const { t, language } = useI18n();
  // A cover that fails to load becomes the placeholder; the card itself never becomes unusable (INV-28).
  const [failed, setFailed] = useState<string | null>(null);
  const coverRef = useRef<HTMLSpanElement>(null);
  const [nearViewport, setNearViewport] = useState(false);
  // Native lazy loading fetches well beyond the viewport. A crowded Search can otherwise start many
  // cover requests at once, all competing for the same source's limited request slots.
  useEffect(() => {
    if (!work.cover_url || nearViewport) return;
    const node = coverRef.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setNearViewport(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setNearViewport(true);
        observer.disconnect();
      }
    }, { rootMargin: "240px 0px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [work.cover_url, nearViewport]);
  const showCover = work.cover_url && failed !== work.cover_url;
  const languages = Object.entries(work.availability ?? {});
  const sources = languages.reduce((total, [, count]) => total + count, 0);
  const href = work.work_id ? `/works/${work.work_id}` : undefined;
  const percent = work.fraction === null || work.fraction === undefined ? null : Math.round(work.fraction * 100);

  const cover = (
    <span className="workcard__cover" ref={coverRef}>
      <span className="workcard__pages" aria-hidden="true" />
      <span className="workcard__face">
        <CoverPlaceholder title={work.title} className="workcard__blank" />
        {showCover && nearViewport &&
          <img src={work.cover_url!} alt="" loading="lazy" decoding="async" fetchPriority="high"
               onError={() => setFailed(work.cover_url ?? null)} />}
      </span>
    </span>
  );

  const caption = (
    <span className="workcard__caption">
      <span className="workcard__title" dir="auto">{work.title}</span>
      {size !== "compact" && (
        <span className="workcard__meta">
          {work.content_type && <span className="workcard__kind">{work.content_type}</span>}
          {languages.length > 0 && (
            <span>{languages.map(([code]) => languageName(code, language)).join(" · ")}</span>
          )}
          {sources > 0 && <span>{sources === 1 ? t("work.source") : t("work.sources", { count: sources })}</span>}
        </span>
      )}
      {problem && <span className="notice notice--problem resultcard__problem" role="alert">{problem}</span>}
      {percent !== null && (
        <span className="workcard__progress">
          <span className="workcard__track"><span style={{ inlineSize: `${percent}%` }} /></span>
          <span className="workcard__percent">{`${percent}%`}</span>
        </span>
      )}
    </span>
  );

  if (href) return <Link to={href} className={`workcard workcard--${size}`}>{cover}{caption}</Link>;
  if (onOpen) {
    return (
      <button type="button" className={`workcard workcard--${size} workcard--open`} onClick={onOpen}
              aria-busy={busy || undefined} disabled={busy}>{cover}{caption}</button>
    );
  }
  return <span className={`workcard workcard--${size}`}>{cover}{caption}</span>;
}
