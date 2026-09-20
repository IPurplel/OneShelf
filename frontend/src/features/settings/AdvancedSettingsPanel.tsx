import { useState } from "react";

import { ApiError, api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import { bytes } from "@/lib/format";
import { Advanced } from "./Advanced";

type Diagnostics = {
  entries: number;
  size_bytes: number;
  oldest_day: string | null;
  max_bytes: number;
  max_age_days: number;
  directory: string;
};

type AuthState = {
  access: string;
  network: { trusted_networks: string[]; trusted_proxies: string[]; gateway_warning: { message: string } | null };
};

/**
 * Advanced settings (Master §32.14, §45, §28.1–28.2; ledger A2).
 *
 * The technical boundary of the install: which networks are trusted, and which proxies may speak for a
 * client. Both are validated by the library, never taken on the UI's word, because widening them widens
 * who can reach the library without a passkey.
 */
export function AdvancedSettingsPanel() {
  const { t } = useI18n();
  const { data, reload } = useResource<AuthState>("/api/auth/state");
  const { data: diagnostics, reload: reloadDiagnostics } = useResource<Diagnostics>("/api/diagnostics");
  const [networks, setNetworks] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  if (data === null) return <section className="paper"><p>{t("state.loading")}</p></section>;
  const current = networks ?? data.network.trusted_networks.join("\n");

  const save = async () => {
    setProblem(null);
    setSaved(false);
    try {
      await api.post("/api/auth/networks", {
        trusted_networks: current.split("\n").map((line) => line.trim()).filter(Boolean),
      });
      setSaved(true);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      reload();
    }
  };

  return (
    <section className="paper">
      <h2 className="display">{t("settings.advanced")}</h2>
      <p className="firstrun__lede">{t("settings.advanced.help")}</p>

      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {saved && <p className="notice" role="status">{t("settings.advanced.saved")}</p>}
      {data.network.gateway_warning !== null && (
        <p className="notice notice--problem">{data.network.gateway_warning.message}</p>
      )}

      <dl className="details">
        <dt>{t("settings.advanced.access")}</dt><dd>{t(`settings.advanced.access.${data.access}` as never)}</dd>
      </dl>

      <label className="field__label">
        {t("settings.advanced.networks")}
        <textarea className="field field--area" rows={4} value={current}
                  onChange={(event) => setNetworks(event.target.value)} />
      </label>
      <p className="cards__meta">{t("settings.advanced.networksHelp")}</p>

      <div className="firstrun__actions">
        <button type="button" className="button button--primary" onClick={() => void save()}>
          {t("settings.advanced.save")}
        </button>
      </div>

      <Advanced label={t("settings.advanced.diagnostics")}>
        {diagnostics === null ? <p>{t("state.loading")}</p> : (
          <>
            <p>{t("settings.advanced.diagnosticsHelp")}</p>
            <ul className="restore__counts">
              <li>{t("settings.advanced.diagnosticsCount", { entries: diagnostics.entries })}</li>
              <li>{t("settings.advanced.diagnosticsSize", { size: bytes(diagnostics.size_bytes),
                                                            cap: bytes(diagnostics.max_bytes) })}</li>
              <li>{t("settings.advanced.diagnosticsAge", { days: diagnostics.max_age_days })}</li>
            </ul>
            <p className="cards__meta">{t("settings.advanced.diagnosticsLocal")}</p>
            <div className="firstrun__actions">
              <button type="button" className="button"
                      onClick={() => { void api.delete("/api/diagnostics").finally(reloadDiagnostics); }}>
                {t("settings.advanced.diagnosticsClear")}
              </button>
            </div>
          </>
        )}
      </Advanced>
    </section>
  );
}
