import { useState } from "react";
import { Link } from "react-router-dom";

import { useI18n } from "@/i18n/i18n";

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
 * The cover stays dominant and stands on the shelf; below the plank come the title, the kind of work,
 * and — when there is progress — a slim olive bar with its percentage. Availability stays concise: a
 * language and a source count, never every internal state.
 */
export function WorkCard({ work, size = "standard", onOpen, busy = false }: {
  work: CardWork;
  size?: "compact" | "standard" | "detailed";
  /** For a result with no Work yet: the card is a button that opens it (see ResultCard). */
  onOpen?: () => void;
  busy?: boolean;
}) {
  const { t, language } = useI18n();
  // A cover that fails to load becomes the placeholder; the card itself never becomes unusable (INV-28).
  const [failed, setFailed] = useState<string | null>(null);
  const showCover = work.cover_url && failed !== work.cover_url;
  const languages = Object.entries(work.availability ?? {});
  const sources = languages.reduce((total, [, count]) => total + count, 0);
  const href = work.work_id ? `/works/${work.work_id}` : undefined;
  const percent = work.fraction === null || work.fraction === undefined ? null : Math.round(work.fraction * 100);

  const cover = (
    <span className="workcard__cover">
      {showCover
        ? <img src={work.cover_url!} alt="" loading="lazy" onError={() => setFailed(work.cover_url ?? null)} />
        : <span className="workcard__blank" aria-hidden="true">{work.title.slice(0, 1)}</span>}
    </span>
  );

  const caption = (
    <span className="workcard__caption">
      <span className="workcard__title">{work.title}</span>
      {size !== "compact" && (
        <span className="workcard__meta">
          {work.content_type && <span className="workcard__kind">{work.content_type}</span>}
          {languages.length > 0 && (
            <span>{languages.map(([code]) => displayLanguage(code, language)).join(" · ")}</span>
          )}
          {sources > 0 && <span>{sources === 1 ? t("work.source") : t("work.sources", { count: sources })}</span>}
        </span>
      )}
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

function displayLanguage(code: string, uiLanguage: string): string {
  try {
    return new Intl.DisplayNames([uiLanguage], { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}
