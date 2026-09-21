import { useState } from "react";

import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { Drawer } from "@/components/Drawer";
import { InstallPanel } from "./InstallPanel";
import { LoginSession } from "./LoginSession";
import { useI18n } from "@/i18n/i18n";
import { useLive } from "@/app/live";

type Source = {
  id: string;
  name: string;
  state: "active" | "disabled" | "pending_review" | "failed";
  version: string | null;
  trust_label: string;
  channel: string;
  capabilities: string[];
  auth_available: boolean;
  session_state: string;
};

/**
 * Sources (Master §21, §32.12): an elegant administrative list, loosely a library catalogue card.
 * What the source does and how it is doing belongs on the row; versions, channels and trust labels
 * belong behind More.
 */
export function SourcesScreen() {
  const { t } = useI18n();
  const { data, reload } = useResource<{ sources: Source[] }>("/api/sources");

  // §21, §36: a session that connects or expires elsewhere shows here without a refresh.
  useLive(["source.session"], reload);
  const [open, setOpen] = useState<Source | null>(null);
  const [signingIn, setSigningIn] = useState<Source | null>(null);

  const sources = data?.sources ?? [];

  const act = async (call: Promise<unknown>) => {
    try {
      await call;
    } finally {
      setOpen(null);
      reload();
    }
  };

  return (
    <section className="screen">
      <h1 className="screen__title">{t("sources.title")}</h1>

      {data !== null && sources.length === 0 && <p className="shelf__empty">{t("sources.empty")}</p>}

      <ul className="cards">
        {sources.map((source) => (
          <li key={source.id} className="cards__row">
            <span className="cards__name display">{source.name}</span>
            <span className="cards__meta">{source.capabilities.join(" · ")}</span>
            {/* It came with OneShelf: the person did not have to add it, and may still remove it. */}
            {source.channel === "bundled" && <span className="chip chip--static">{t("sources.bundled")}</span>}
            <span className={`cards__state cards__state--${source.state}`}>
              {t(`sources.state.${source.state}` as const)}
            </span>
            {source.session_state === "expired" && <span className="cards__warn">{t("sources.reconnect")}</span>}
            {source.session_state === "connected" && <span className="cards__ok">{t("sources.connected")}</span>}
            <button type="button" className="chip" onClick={() => setOpen(source)}>{t("sources.more")}</button>
          </li>
        ))}
      </ul>

      {open !== null && (
        <Drawer title={open.name} onClose={() => setOpen(null)}>
          <dl className="details">
            <dt>{t("sources.version")}</dt><dd>{open.version ?? "—"}</dd>
            <dt>{t("sources.channel")}</dt><dd>{open.channel}</dd>
            <dt>{t("sources.trust")}</dt><dd>{open.trust_label}</dd>
            <dt>{t("sources.capabilities")}</dt><dd>{open.capabilities.join(", ")}</dd>
          </dl>
          <div className="drawer__actions">
            {open.state === "active" ? (
              <button type="button" className="button"
                      onClick={() => void act(api.post(`/api/sources/${open.id}/disable`))}>
                {t("sources.disable")}
              </button>
            ) : (
              <button type="button" className="button"
                      onClick={() => void act(api.post(`/api/sources/${open.id}/enable`))}>
                {t("sources.enable")}
              </button>
            )}
            <button type="button" className="button"
                    onClick={() => void act(api.post(`/api/sources/${open.id}/rollback`))}>
              {t("sources.rollback")}
            </button>
            {open.auth_available && (
              <button type="button" className="button"
                      onClick={() => { setSigningIn(open); setOpen(null); }}>
                {t("sources.useMySession")}
              </button>
            )}
            {open.auth_available && open.session_state !== "none" && (
              <button type="button" className="button"
                      onClick={() => void act(api.delete(`/api/sources/${open.id}/session`))}>
                {t("sources.disconnect")}
              </button>
            )}
          </div>
        </Drawer>
      )}

      {signingIn !== null && (
        <LoginSession sourceId={signingIn.id} sourceName={signingIn.name}
                      onClose={() => { setSigningIn(null); reload(); }} />
      )}

      <InstallPanel onInstalled={reload} />
    </section>
  );
}
