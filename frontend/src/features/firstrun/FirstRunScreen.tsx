import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";

type Step = "welcome" | "storage" | "access_mode" | "sources" | "finish";
type Mode = "local" | "lan" | "remote";

type FirstRunState = {
  state: "pending" | "completed";
  access_mode: Mode | null;
  storage: { id: string; name: string; path: string; default: boolean }[];
  remote: { canonical_hostname: string | null; passkey_registered: boolean };
  sources_installed: number;
};

/**
 * First Run (Master §29, §32.17).
 *
 * Short on purpose, and never a gate: the library is reachable from the first moment, so every step
 * offers a way straight to it. Only the Remote path asks for a hostname, and sources are plainly
 * optional — files you already have need none.
 */
export function FirstRunScreen({ initialStep = "welcome" }: { initialStep?: Step }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { data, reload } = useResource<FirstRunState>("/api/first-run");
  const [step, setStep] = useState<Step>(initialStep);
  const [mode, setMode] = useState<Mode>("local");
  const [path, setPath] = useState("");
  const [name, setName] = useState("Library");
  const [networks, setNetworks] = useState("");
  const [hostname, setHostname] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (data?.access_mode) setMode(data.access_mode);
  }, [data?.access_mode]);

  const run = async (call: Promise<unknown>, next: Step) => {
    setProblem(null);
    try {
      await call;
      reload();
      setStep(next);
      return true;
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
      return false;
    }
  };

  return (
    <section className="firstrun">
      <div className="firstrun__panel paper">
        {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}

        {step === "welcome" && (
          <>
            <h1 className="firstrun__title display">{t("first.welcome")}</h1>
            <p className="firstrun__lede">{t("first.tagline")}</p>
            <div className="firstrun__actions">
              <button type="button" className="button button--primary" onClick={() => setStep("storage")}>
                {t("first.continue")}
              </button>
              <Link className="button" to="/">{t("first.skip")}</Link>
            </div>
          </>
        )}

        {step === "storage" && (
          <>
            <h1 className="firstrun__title display">{t("first.storage.title")}</h1>
            <p className="firstrun__lede">{t("first.storage.help")}</p>
            <label className="field__label">
              {t("first.storage.field")}
              <input type="text" className="field" value={path} onChange={(event) => setPath(event.target.value)} />
            </label>
            <label className="field__label">
              {t("first.storage.name")}
              <input type="text" className="field" value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <div className="firstrun__actions">
              <button type="button" className="button" onClick={() => setStep("welcome")}>{t("first.back")}</button>
              <button type="button" className="button button--primary"
                      onClick={() => void run(api.post("/api/first-run/storage", { name, path }), "access_mode")}>
                {t("first.continue")}
              </button>
              <Link className="button" to="/">{t("first.skip")}</Link>
            </div>
          </>
        )}

        {step === "access_mode" && (
          <>
            <h1 className="firstrun__title display">{t("first.access.title")}</h1>
            <fieldset className="panel__group" role="radiogroup" aria-label={t("first.access.title")}>
              {(["local", "lan", "remote"] as Mode[]).map((candidate) => (
                <label key={candidate} className="panel__choice">
                  <input type="radio" name="mode" value={candidate} checked={mode === candidate}
                         onChange={() => setMode(candidate)} />
                  <span>
                    <span className="panel__choiceTitle">{t(`first.access.${candidate}` as const)}</span>
                    <span className="panel__choiceHelp">{t(`first.access.${candidate}Help` as const)}</span>
                  </span>
                </label>
              ))}
            </fieldset>

            {mode === "lan" && (
              <label className="field__label">
                {t("first.access.networks")}
                <textarea className="field field--area" value={networks} rows={3}
                          onChange={(event) => setNetworks(event.target.value)} />
              </label>
            )}

            {mode === "remote" && (
              <label className="field__label">
                {t("first.access.hostname")}
                <input type="text" className="field" value={hostname}
                       onChange={(event) => setHostname(event.target.value)} />
              </label>
            )}

            <div className="firstrun__actions">
              <button type="button" className="button" onClick={() => setStep("storage")}>{t("first.back")}</button>
              <button type="button" className="button button--primary"
                      onClick={() => void run(api.post("/api/first-run/access-mode", {
                        mode,
                        trusted_networks: mode === "lan"
                          ? networks.split("\n").map((line) => line.trim()).filter(Boolean) : undefined,
                        canonical_hostname: mode === "remote" ? hostname.trim() : undefined,
                      }), "sources")}>
                {t("first.continue")}
              </button>
            </div>
          </>
        )}

        {step === "sources" && (
          <>
            <h1 className="firstrun__title display">{t("first.sources.title")}</h1>
            <p className="firstrun__lede">
              {data !== null && data.sources_installed > 0
                ? t("first.sources.included", { count: data.sources_installed })
                : t("first.sources.body")}
            </p>
            <div className="firstrun__actions">
              <Link className="button" to="/sources">{t("nav.sources")}</Link>
              <button type="button" className="button button--primary" onClick={() => setStep("finish")}>
                {t("first.continue")}
              </button>
            </div>
          </>
        )}

        {step === "finish" && (
          <>
            <h1 className="firstrun__title display">{t("first.finish.title")}</h1>
            <p className="firstrun__lede">{t("first.finish.body")}</p>
            <div className="firstrun__actions">
              <button type="button" className="button button--primary"
                      onClick={() => void run(api.post("/api/first-run/finish"), "finish")
                        .then((ok) => { if (ok) navigate("/"); })}>
                {t("first.finish.go")}
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
