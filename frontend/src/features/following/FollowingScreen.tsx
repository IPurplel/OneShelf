import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import { useLive } from "@/app/live";

type Follow = {
  work_id: string;
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
  const { t } = useI18n();
  const { data, reload } = useResource<{ follows: Follow[] }>("/api/follows");

  // §20, §36: a check that finishes elsewhere lands here without waiting for a refresh.
  useLive(["follow.changed", "follow.releases"], reload);
  const [busy, setBusy] = useState(false);

  const follows = data?.follows ?? [];
  const fresh = follows.filter((follow) => follow.unseen_releases > 0);
  const attention = follows.filter((follow) => follow.unseen_releases === 0
    && ["degraded", "catalog_suspicious", "reconnect_required"].includes(follow.state));
  const current = follows.filter((follow) => !fresh.includes(follow) && !attention.includes(follow));

  const check = async (call: Promise<unknown>) => {
    setBusy(true);
    try {
      await call;
    } finally {
      setBusy(false);
      reload();
    }
  };

  return (
    <section className="screen">
      <div className="screen__head">
        <h1 className="screen__title">{t("follow.title")}</h1>
        <button type="button" className="button" disabled={busy}
                onClick={() => void check(api.post("/api/follows/check-all"))}>
          {t("follow.checkAll")}
        </button>
      </div>

      {data !== null && follows.length === 0 && <p className="shelf__empty">{t("follow.empty")}</p>}

      <Section id="new" title={t("follow.new")} follows={fresh} onCheck={check} />
      <Section id="attention" title={t("follow.attention")} follows={attention} onCheck={check} />
      <Section id="current" title={t("follow.current")} follows={current} onCheck={check} />
    </section>
  );
}

function Section({ id, title, follows, onCheck }: {
  id: string;
  title: string;
  follows: Follow[];
  onCheck: (call: Promise<unknown>) => void;
}) {
  const { t } = useI18n();
  if (follows.length === 0) return null;

  return (
    <section className="journal" role="region" aria-label={title}>
      <h2 className="journal__title display" id={`${id}-title`}>{title}</h2>
      <ul className="journal__rows">
        {follows.map((follow) => (
          <li key={follow.work_id} className="journal__row">
            <Link className="journal__work" to={`/works/${follow.work_id}`}>{follow.work_id}</Link>
            <span className="journal__source">{follow.source_id} · {follow.language}</span>
            {follow.unseen_releases > 0 && (
              <span className="journal__badge">{t("follow.count", { count: follow.unseen_releases })}</span>
            )}
            {follow.state !== "up_to_date" && follow.unseen_releases === 0 && (
              <span className="journal__state">{t(`follow.state.${follow.state}` as const)}</span>
            )}
            <span className="journal__when">
              {t("follow.lastAnswered", { when: relative(follow.last_successful_at) })}
            </span>
            <button type="button" className="chip"
                    onClick={() => onCheck(api.post(`/api/follows/${follow.work_id}/check`))}>
              {t("follow.check")}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function relative(when: string | null): string {
  if (when === null) return "—";
  const date = new Date(when);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString();
}
