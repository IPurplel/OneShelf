import { useState } from "react";

import { ApiError, api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useI18n } from "@/i18n/i18n";

type AuthState = {
  canonical_hostname: string | null;
  remote_enabled: boolean;
  passkeys: { credential_id: string; label: string; created_at: string; last_used_at: string | null;
              backed_up: boolean }[];
  sessions: { id: string; label: string; created_at: string; last_active_at: string;
              expires_at: string | null; current: boolean }[];
  recovery: { configured: boolean; created_at: string | null; last_used_at: string | null };
  access: string;
  network: { trusted_networks: string[]; trusted_proxies: string[];
             gateway_warning: { message: string } | null };
  session_lifetimes: string[];
};

/** The browser owns the WebAuthn ceremony; OneShelf only ever sees its result (Master §28.3). */
type WebAuthnStatics = { parseCreationOptionsFromJSON(json: unknown): PublicKeyCredentialCreationOptions };

/**
 * Remote access (Master §28, §32.14).
 *
 * With no hostname, this says plainly that remote access is not set up and what answers today. A passkey
 * can only be registered once the canonical hostname is settled, because the credential is bound to it.
 * The Recovery Code is shown exactly once, and resetting remote access spells out what it clears and what
 * it leaves completely alone.
 */
export function RemotePanel() {
  const { t } = useI18n();
  const { data, reload } = useResource<AuthState>("/api/auth/state");
  const [hostname, setHostname] = useState("");
  const [label, setLabel] = useState("");
  const [freshCode, setFreshCode] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const say = (error: unknown) =>
    setProblem(error instanceof ApiError || error instanceof Error ? error.message : t("state.offline"));

  const run = async (call: Promise<unknown>) => {
    setProblem(null);
    try {
      await call;
    } catch (error) {
      say(error);
    } finally {
      reload();
    }
  };

  const addPasskey = async () => {
    setProblem(null);
    try {
      const ceremony = await api.post<{ ceremony_id: string; options: unknown }>(
        "/api/auth/passkeys/register/options", { label: label || "Passkey" });
      const statics = PublicKeyCredential as unknown as WebAuthnStatics;
      const credential = await navigator.credentials.create({
        publicKey: statics.parseCreationOptionsFromJSON(ceremony.options),
      }) as (PublicKeyCredential & { toJSON(): unknown }) | null;
      if (credential === null) throw new Error(t("remote.cancelled"));
      const enrolment = await api.post<{ recovery_code: string | null }>("/api/auth/passkeys/register", {
        ceremony_id: ceremony.ceremony_id, label: label || "Passkey", response: credential.toJSON(),
      });
      if (enrolment.recovery_code !== null) setFreshCode(enrolment.recovery_code);
      setMessage(t("remote.passkeyAdded"));
      setLabel("");
    } catch (error) {
      say(error);
    } finally {
      reload();
    }
  };

  if (data === null) return <section className="paper"><p>{t("state.loading")}</p></section>;

  return (
    <section className="paper">
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {message !== null && <p className="notice" role="status">{message}</p>}
      {data.network.gateway_warning !== null && (
        <p className="notice notice--problem">{data.network.gateway_warning.message}</p>
      )}

      {data.canonical_hostname === null ? (
        <>
          <p>{t("settings.remote.none")}</p>
          <p className="firstrun__lede">{t("remote.hostHelp")}</p>
          <label className="field__label">
            {t("settings.remote.host")}
            <input type="text" className="field" value={hostname} placeholder="oneshelf.example.net"
                   onChange={(event) => setHostname(event.target.value)} />
          </label>
          <div className="firstrun__actions">
            <button type="button" className="button button--primary"
                    onClick={() => void run(api.post("/api/auth/hostname", { hostname: hostname.trim() }))}>
              {t("remote.saveHost")}
            </button>
          </div>
        </>
      ) : (
        <>
          <dl className="details">
            <dt>{t("settings.remote.host")}</dt><dd>{data.canonical_hostname}</dd>
          </dl>

          <h3 className="display">{t("settings.remote.passkeys")}</h3>
          {data.passkeys.length === 0 && <p className="shelf__empty">{t("remote.noPasskeys")}</p>}
          <ul className="cards">
            {data.passkeys.map((passkey) => (
              <li key={passkey.credential_id} className="cards__row">
                <span className="cards__name display">{passkey.label}</span>
                <span className="cards__meta">{new Date(passkey.created_at).toLocaleDateString()}</span>
                <button type="button" className="chip"
                        onClick={() => void run(api.delete(`/api/auth/passkeys/${passkey.credential_id}`))}>
                  {t("remote.removePasskey")}
                </button>
              </li>
            ))}
          </ul>
          <label className="field__label">
            {t("remote.passkeyLabel")}
            <input type="text" className="field" value={label}
                   onChange={(event) => setLabel(event.target.value)} />
          </label>
          <div className="firstrun__actions">
            <button type="button" className="button button--primary" onClick={() => void addPasskey()}>
              {t("remote.addPasskey")}
            </button>
          </div>
          <p className="cards__meta">{t("remote.addFromHere")}</p>

          <h3 className="display">{t("settings.remote.sessions")}</h3>
          {data.sessions.length === 0 && <p className="shelf__empty">{t("remote.noSessions")}</p>}
          <ul className="cards">
            {data.sessions.map((session) => (
              <li key={session.id} className="cards__row">
                <span className="cards__name display">{session.label}</span>
                <span className="cards__meta">
                  {t("remote.lastActive", { when: new Date(session.last_active_at).toLocaleString() })}
                </span>
                {session.current && <span className="cards__ok">{t("remote.thisDevice")}</span>}
                <button type="button" className="chip"
                        onClick={() => void run(api.delete(`/api/auth/sessions/${session.id}`))}>
                  {t("remote.signOut")}
                </button>
              </li>
            ))}
          </ul>

          <h3 className="display">{t("remote.recovery")}</h3>
          <p>{data.recovery.configured ? t("remote.recoverySet") : t("remote.recoveryNone")}</p>
          {freshCode !== null && (
            <div className="remote__code">
              <code className="remote__codeValue">{freshCode}</code>
              <p>{t("remote.codeOnce")}</p>
              <p>{t("remote.codeReplaces")}</p>
            </div>
          )}
          <div className="firstrun__actions">
            <button type="button" className="button"
                    onClick={() => void run(api.post<{ recovery_code: string }>("/api/auth/recovery/regenerate")
                      .then((result) => setFreshCode(result.recovery_code)))}>
              {t("remote.newCode")}
            </button>
            <button type="button" className="button" onClick={() => setResetting(true)}>
              {t("remote.reset")}
            </button>
          </div>
        </>
      )}

      {resetting && (
        <ConfirmDialog title={t("remote.reset")} body={t("remote.resetBody")} confirmLabel={t("remote.reset")}
                       onCancel={() => setResetting(false)}
                       onConfirm={() => { setResetting(false); void run(api.post("/api/auth/lan-recovery")); }} />
      )}
    </section>
  );
}
