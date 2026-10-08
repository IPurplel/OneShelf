import { useState } from "react";

import { api } from "@/api/client";
import { apiErrorText } from "@/i18n/apiErrors";
import { useResource } from "@/api/useApi";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Drawer } from "@/components/Drawer";
import { LoadingState } from "@/components/LoadingState";
import { InstallPanel } from "./InstallPanel";
import { LoginSession } from "./LoginSession";
import { RegistryPanel } from "./RegistryPanel";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";
import { capabilityLabel, channelLabel, trustLabel } from "@/i18n/sourceLabels";
import { useLive } from "@/app/live";

type Source = {
  id: string;
  name: string;
  state: "active" | "disabled" | "pending_review" | "failed" | "uninstalled";
  version: string | null;
  trust_label: string;
  channel: string;
  capabilities: string[];
  auth_available: boolean;
  session_state: string;
  can_rollback: boolean;
};

/** Where an installed source came from, and whether a trusted signature stands behind it. */
function originKey(source: Source): StringKey | null {
  if (source.channel === "bundled") return "sources.bundled";
  if (source.channel === "registry") {
    if (source.trust_label === "official") return "sources.origin.registry";
    return source.trust_label === "verified_community" ? "sources.origin.registryVerified"
      : "sources.origin.registryCommunity";
  }
  if (source.channel === "upload") return "sources.origin.upload";
  return null;
}

/**
 * Sources (Master §21, §32.12): an elegant administrative list, loosely a library catalogue card.
 * What the source does and how it is doing belongs on the row; versions, channels and trust labels
 * belong behind More.
 */
export function SourcesScreen() {
  const { t, language } = useI18n();
  const { data, error, loading, reload } = useResource<{ sources: Source[] }>("/api/sources");

  // §21, §36: a session that connects or expires elsewhere shows here without a refresh.
  useLive(["source.session"], reload);
  const [open, setOpen] = useState<Source | null>(null);
  const [signingIn, setSigningIn] = useState<Source | null>(null);
  const [removing, setRemoving] = useState<Source | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  // Anything that changes what is installed changes what the Registry section should say.
  const [revision, setRevision] = useState(0);
  const changed = () => { reload(); setRevision((n) => n + 1); };

  // A removed source keeps its record (provenance), but it is not installed: the Registry section offers it.
  const sources = (data?.sources ?? []).filter((source) => source.state !== "uninstalled");

  const act = async (call: Promise<unknown>) => {
    setProblem(null);
    try {
      await call;
      setOpen(null);
    } catch (error) {
      setProblem(apiErrorText(error, language, t));
      setOpen(null);
    } finally {
      changed();
    }
  };

  return (
    <section className="screen">
      <h1 className="screen__title">{t("sources.title")}</h1>
      <h2 className="display">{t("sources.installed")}</h2>

      {error !== null && <><p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button></>}
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {loading && <LoadingState />}

      {data !== null && !loading && sources.length === 0 && <p className="shelf__empty">{t("sources.empty")}</p>}

      <ul className="cards">
        {sources.map((source) => (
          <li key={source.id} className="cards__row">
            <span className="cards__name display">{source.name}</span>
            <span className="cards__meta">{source.capabilities.map(value => capabilityLabel(value, t)).join(" · ")}</span>
            {/* Where it came from: bundled with OneShelf, the Registry, or a file the person chose. */}
            {originKey(source) !== null && <span className="chip chip--static">{t(originKey(source)!)}</span>}
            <span className={`cards__state cards__state--${source.state}`}>
              {t(`sources.state.${source.state}` as const)}
            </span>
            {source.session_state === "expired" && <span className="cards__warn">{t("sources.reconnect")}</span>}
            {source.session_state === "connected" && <span className="cards__ok">{t("sources.connected")}</span>}
            <button type="button" className="chip" disabled={loading} onClick={() => setOpen(source)}>{t("sources.more")}</button>
          </li>
        ))}
      </ul>

      {open !== null && (
        <Drawer title={open.name} onClose={() => setOpen(null)}>
          <dl className="details">
            <dt>{t("sources.version")}</dt><dd>{open.version ?? "—"}</dd>
            <dt>{t("sources.channel")}</dt><dd>{channelLabel(open.channel, t)}</dd>
            <dt>{t("sources.trust")}</dt><dd>{trustLabel(open.trust_label, t)}</dd>
            <dt>{t("sources.capabilities")}</dt><dd>{open.capabilities.map(value => capabilityLabel(value, t)).join(", ")}</dd>
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
            {open.can_rollback && (
              <button type="button" className="button"
                      onClick={() => void act(api.post(`/api/sources/${open.id}/rollback`))}>
                {t("sources.rollback")}
              </button>
            )}
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
            <button type="button" className="button" onClick={() => { setRemoving(open); setOpen(null); }}>
              {t("sources.remove")}
            </button>
          </div>
        </Drawer>
      )}

      {signingIn !== null && (
        <LoginSession sourceId={signingIn.id} sourceName={signingIn.name}
                      onClose={() => { setSigningIn(null); reload(); }} />
      )}

      {removing !== null && (
        <ConfirmDialog title={t("sources.removeConfirm.title", { name: removing.name })}
                       body={t("sources.removeConfirm.body")}
                       confirmLabel={t("sources.removeConfirm.action")}
                       onCancel={() => setRemoving(null)}
                       onConfirm={() => {
                         const target = removing;
                         setRemoving(null);
                         void act(api.delete(`/api/sources/${target.id}`));
                       }} />
      )}

      <RegistryPanel revision={revision} onChanged={changed} />

      <InstallPanel onInstalled={changed} />
    </section>
  );
}
