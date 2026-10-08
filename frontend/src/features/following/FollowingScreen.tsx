import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import { languageName } from "@/i18n/language";
import { useLive } from "@/app/live";
import { workLink } from "@/features/reader/links";
import { LoadingState } from "@/components/LoadingState";

type Follow = {
  work_id: string;
  work_title: string;
  track_id: string;
  source_id: string;
  language: string;
  state: "up_to_date" | "new_releases" | "degraded" | "catalog_suspicious" | "reconnect_required" | "checking";
  last_attempted_at: string | null;
  last_successful_at: string | null;
  unseen_releases: number;
};

/** Following (Master §20, §32.10): a reading journal on warm paper rows. No charts, ever. */
export function FollowingScreen() {
  const { t, language } = useI18n();
  const { data, error, loading, reload } = useResource<{ follows: Follow[] }>("/api/follows");

  // §20, §36: a check that finishes elsewhere lands here without waiting for a refresh.
  useLive(["follow.changed", "follow.releases"], reload);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const follows = data?.follows ?? [];
  const fresh = follows.filter((follow) => follow.unseen_releases > 0);
  const attention = follows.filter((follow) => follow.unseen_releases === 0
    && ["degraded", "catalog_suspicious", "reconnect_required"].includes(follow.state));
  const current = follows.filter((follow) => !fresh.includes(follow) && !attention.includes(follow));

  const check = async (call: Promise<unknown>) => {
    setBusy(true);
    setProblem(null);
    try {
      await call;
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      setBusy(false);
      reload();
    }
  };

  return (
    <section className="screen">
      <div className="screen__head">
        <h1 className="screen__title">{t("follow.title")}</h1>
        {data !== null && follows.length > 0 && (
          <button type="button" className="button" disabled={busy || loading}
                  onClick={() => void check(api.post("/api/follows/check-all"))}>
            {t("follow.checkAll")}
          </button>
        )}
      </div>

      {error !== null && <><p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button></>}
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {loading && <LoadingState />}

      {data !== null && !loading && follows.length === 0 && <div className="empty">
        <p className="empty__body">{t("follow.empty")}</p>
        <Link className="button button--primary" to="/search">{t("follow.findWorks")}</Link>
      </div>}

      <Section id="new" title={t("follow.new")} follows={fresh} onCheck={check} language={language} disabled={busy || loading} />
      <Section id="attention" title={t("follow.attention")} follows={attention} onCheck={check} language={language} disabled={busy || loading} />
      <Section id="current" title={t("follow.current")} follows={current} onCheck={check} language={language} disabled={busy || loading} />
    </section>
  );
}

function Section({ id, title, follows, onCheck, language, disabled }: {
  id: string;
  title: string;
  follows: Follow[];
  onCheck: (call: Promise<unknown>) => void;
  language: "en" | "ar";
  disabled: boolean;
}) {
  const { t } = useI18n();
  if (follows.length === 0) return null;

  return (
    <section className="journal" role="region" aria-label={title}>
      <h2 className="journal__title display" id={`${id}-title`}>{title}</h2>
      <ul className="journal__rows">
        {follows.map((follow) => (
          <li key={`${follow.work_id}:${follow.language}`} className="journal__row">
            <Link className="journal__work" to={workLink(follow.work_id, follow.track_id)}>{follow.work_title}</Link>
            <span className="journal__source">{follow.source_id} · {languageName(follow.language, language)}</span>
            {follow.unseen_releases > 0 && (
              <span className="journal__badge">{t("follow.count", { count: follow.unseen_releases })}</span>
            )}
            {follow.state !== "up_to_date" && follow.unseen_releases === 0 && (
              <span className="journal__state">{t(`follow.state.${follow.state}` as const)}</span>
            )}
            <span className="journal__when">
              {t("follow.lastAnswered", { when: relative(follow.last_successful_at, language) })}
            </span>
            <button type="button" className="chip" disabled={disabled}
                    onClick={() => onCheck(api.post(`/api/follows/${follow.work_id}/check?${new URLSearchParams({ language: follow.language })}`))}>
              {t("follow.check")}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function relative(when: string | null, language: "en" | "ar"): string {
  if (when === null) return "—";
  const date = new Date(when);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(language);
}
