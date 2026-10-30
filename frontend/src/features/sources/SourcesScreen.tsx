import { useId, useState } from "react";

import { motion } from "motion/react";

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
import { TRANSITION_EASE, useReducedMotion } from "@/lib/motion";
import { CATEGORIES, categoryLabel, languageLabel } from "@/features/search/scopes";

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
  category?: string | null;
  languages?: string[];
  /** Aggregate overall health-check success; null means checked never, omitted means legacy/unknown API. */
  last_successful_check_at?: string | null;
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
  const installedHeading = useId();
  const { data, error, loading, reload } = useResource<{ sources: Source[] }>("/api/sources");

  // §21, §36: a session that connects or expires elsewhere shows here without a refresh.
  useLive(["source.session", "source.health"], reload);
  const [open, setOpen] = useState<Source | null>(null);
  const [signingIn, setSigningIn] = useState<Source | null>(null);
  const [removing, setRemoving] = useState<Source | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [sourceLanguage, setSourceLanguage] = useState<string | null>(null);
  // Anything that changes what is installed changes what the Registry section should say.
  const [revision, setRevision] = useState(0);
  const changed = () => { reload(); setRevision((n) => n + 1); };
  const reduced = useReducedMotion();

  // A removed source keeps its record (provenance), but it is not installed: the Registry section offers it.
  const sources = (data?.sources ?? []).filter((source) => source.state !== "uninstalled");
  const categories = Array.from(new Set(sources.map(source => source.category || ""))).sort((a, b) => {
    const aIndex = CATEGORIES.findIndex(value => value === a);
    const bIndex = CATEGORIES.findIndex(value => value === b);
    return (aIndex < 0 ? CATEGORIES.length : aIndex) - (bIndex < 0 ? CATEGORIES.length : bIndex)
      || categoryLabel(a, language).localeCompare(categoryLabel(b, language), language);
  });
  const languages = Array.from(new Set(sources.flatMap(source => source.languages ?? []).map(code => code.toUpperCase())));
  if (sources.some(source => !source.languages?.length)) languages.push("");
  languages.sort((a, b) => a === "AR" ? -1 : b === "AR" ? 1
    : a === "" ? 1 : b === "" ? -1
    : languageLabel(a, language).localeCompare(languageLabel(b, language), language));
  const supportsLanguage = (source: Source, code: string) => code === ""
    ? !source.languages?.length
    : source.languages?.some(value => value.toUpperCase() === code || value.toUpperCase() === "MULTI") ?? false;
  const filtered = sources.filter(source =>
    (category === null || (source.category || "") === category)
    && (sourceLanguage === null || supportsLanguage(source, sourceLanguage)));

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
      <section aria-labelledby={installedHeading}>
      <h2 className="display" id={installedHeading}>{t("sources.installed")}</h2>

      {error !== null && <><p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button></>}
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {loading && <LoadingState />}

      {data !== null && !loading && sources.length === 0 && <p className="shelf__empty">{t("sources.empty")}</p>}
      {data !== null && !loading && sources.length > 0 && <>
        <div className="sources__filters">
          <div className="sources__filter-group" role="group" aria-label={t("registry.categories")}>
            <button type="button" className="chip" aria-pressed={category === null} onClick={() => setCategory(null)}>
              {t("registry.allCategories")} · {sources.length}
            </button>
            {categories.map(value => <button type="button" className="chip" key={value || "unknown"}
              aria-pressed={category === value} onClick={() => setCategory(category === value ? null : value)}>
              {value ? categoryLabel(value, language) : t("sources.unknownCategory")} · {sources.filter(source => (source.category || "") === value).length}
            </button>)}
          </div>
          <div className="sources__filter-group" role="group" aria-label={t("registry.languages")}>
            <button type="button" className="chip" aria-pressed={sourceLanguage === null} onClick={() => setSourceLanguage(null)}>
              {t("sources.allLanguages")}
            </button>
            {languages.map(value => <button type="button" className="chip" key={value || "unknown"}
              aria-pressed={sourceLanguage === value} onClick={() => setSourceLanguage(sourceLanguage === value ? null : value)}>
              {value ? languageLabel(value, language) : t("language.unknown")} · {sources.filter(source => supportsLanguage(source, value)).length}
            </button>)}
          </div>
        </div>
        <p className="cards__meta" role="status">{t("sources.count", { shown: filtered.length, total: sources.length })}</p>
        {filtered.length === 0 && <p className="shelf__empty">{t("sources.noMatch")}</p>}
      </>}

      <ul className="cards">
        {filtered.map((source, i) => (
          <motion.li key={source.id} className="cards__row sources__row"
            initial={reduced ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...TRANSITION_EASE, delay: Math.min(i * 0.04, 0.3) }}
          >
            {/* Name over capabilities, so every row has the same shape however long either is. */}
            <span className="sources__identity">
              <span className="cards__name display" dir="auto">{source.name}</span>
              <span className="cards__meta">{source.capabilities.map(value => capabilityLabel(value, t)).join(" · ")}</span>
            </span>
            {/* Where it came from: bundled with OneShelf, the Registry, or a file the person chose. */}
            {originKey(source) !== null && <span className="chip chip--static">{t(originKey(source)!)}</span>}
            <span className={`cards__state cards__state--${source.state}`}>
              {t(`sources.state.${source.state}` as const)}
            </span>
            <span className="cards__meta sources__lastCheck">
              {t("sources.lastSuccess")}: {source.last_successful_check_at === undefined
                ? t("sources.checkUnknown")
                : source.last_successful_check_at === null
                  ? t("sources.neverChecked")
                  : !Number.isFinite(Date.parse(source.last_successful_check_at)) ? t("sources.checkUnknown")
                  : <time dateTime={source.last_successful_check_at}>{new Intl.DateTimeFormat(language, {
                    dateStyle: "medium", timeStyle: "short",
                  }).format(new Date(source.last_successful_check_at))}</time>}
            </span>
            {source.session_state === "expired" && <span className="cards__warn">{t("sources.reconnect")}</span>}
            {source.session_state === "connected" && <span className="cards__ok">{t("sources.connected")}</span>}
            <button type="button" className="chip" aria-label={t("sources.moreFor", { name: source.name })}
              disabled={loading} onClick={() => setOpen(source)}>{t("sources.more")}</button>
          </motion.li>
        ))}
      </ul>
      </section>

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
            {open.state === "active" && open.auth_available && (
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
