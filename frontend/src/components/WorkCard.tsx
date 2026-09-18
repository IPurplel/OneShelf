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
 * One logical Work, in three sizes (Master §32.6). The cover stays dominant and availability stays
 * concise: a language and a source count, never every internal state.
 */
export function WorkCard({ work, size = "standard" }: { work: CardWork; size?: "compact" | "standard" | "detailed" }) {
  const { t, language } = useI18n();
  const languages = Object.entries(work.availability ?? {});
  const sources = languages.reduce((total, [, count]) => total + count, 0);
  const href = work.work_id ? `/works/${work.work_id}` : undefined;
  const percent = work.fraction === null || work.fraction === undefined ? null : Math.round(work.fraction * 100);

  const body = (
    <>
      <span className="workcard__cover" aria-hidden={work.cover_url ? undefined : "true"}>
        {work.cover_url ? <img src={work.cover_url} alt="" loading="lazy" /> : <span className="workcard__blank" />}
        {percent !== null && (
          <span className="workcard__progress" role="presentation">
            <span style={{ inlineSize: `${percent}%` }} />
          </span>
        )}
      </span>
      <span className="workcard__title display">{work.title}</span>
      {size !== "compact" && (
        <span className="workcard__meta">
          {languages.length > 0 && (
            <span>
              {languages.map(([code]) => new Intl.DisplayNames([language], { type: "language" }).of(code) ?? code)
                .join(" · ")}
            </span>
          )}
          {sources > 0 && <span>{sources === 1 ? t("work.source") : t("work.sources", { count: sources })}</span>}
          {percent !== null && <span>{`${percent}%`}</span>}
        </span>
      )}
    </>
  );

  return href ? (
    <Link to={href} className={`workcard workcard--${size}`}>{body}</Link>
  ) : (
    <span className={`workcard workcard--${size}`}>{body}</span>
  );
}
