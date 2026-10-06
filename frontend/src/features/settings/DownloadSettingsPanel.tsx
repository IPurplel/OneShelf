import { useState } from "react";

import { ApiError, api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";
import { Advanced } from "./Advanced";
import { NumberSetting } from "./NumberSetting";

type DownloadSettings = {
  auto_download: { enabled: boolean; mode: "current" | "read_ahead"; read_ahead: number; threshold: number };
  keep_partial_on_cancel: boolean;
  extraction: { method: string | null; mode: string; fallback_order: string[] };
};

const METHODS = ["direct", "html_api", "reader_media", "browser"] as const;
const MODES = ["preferred_ask", "strict", "automatic"] as const;

/**
 * Download settings (Master §32.14, §45, §19, §16.6, §14).
 *
 * Reading is not downloading: auto-download is off until it is asked for, and when it is on it says
 * exactly how far it reaches. The engine internals — what happens to a partial file on cancel, which
 * method is preferred and what happens when it fails — sit behind Advanced.
 */
export function DownloadSettingsPanel() {
  const { t } = useI18n();
  const { data, error, loading, reload } = useResource<DownloadSettings>("/api/downloads/settings");
  const [problem, setProblem] = useState<string | null>(null);

  const write = async (body: Record<string, unknown>) => {
    setProblem(null);
    try {
      await api.post("/api/downloads/settings", body);
      reload();
    } catch (error) {
      setProblem(t("settings.notSaved", { message: error instanceof ApiError ? error.message : t("state.offline") }));
    }
  };

  if (error !== null && !loading) return <section className="paper">
    <p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
    <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button>
  </section>;
  if (data === null) return <section className="paper"><p>{t("state.loading")}</p></section>;
  const auto = data.auto_download;

  return (
    <section className="paper">
      {problem && <p className="notice notice--problem" role="alert">{problem}</p>}
      <h2 className="display">{t("settings.downloads")}</h2>
      <p className="firstrun__lede">{t("settings.downloads.help")}</p>

      <label className="panel__choice">
        <input type="checkbox" checked={auto.enabled}
               onChange={() => void write({ auto_download: { enabled: !auto.enabled } })} />
        <span>
          <span className="panel__choiceTitle">{t("settings.downloads.auto")}</span>
          <span className="panel__choiceHelp">{t("settings.downloads.autoHelp")}</span>
        </span>
      </label>

      {auto.enabled && (
        <>
          <fieldset className="panel__group" role="radiogroup" aria-label={t("settings.downloads.reach")}>
            <legend>{t("settings.downloads.reach")}</legend>
            {(["current", "read_ahead"] as const).map((mode) => (
              <label key={mode} className="panel__choice">
                <input type="radio" name="auto-mode" value={mode} checked={auto.mode === mode}
                       onChange={() => void write({ auto_download: { mode } })} />
                <span>{t(`settings.downloads.mode.${mode}` as StringKey)}</span>
              </label>
            ))}
          </fieldset>
          {auto.mode === "read_ahead" && (
            <NumberSetting label={t("settings.downloads.readAhead")} value={auto.read_ahead} min={1} max={20}
              onSave={async value => {
                await api.post("/api/downloads/settings", { auto_download: { read_ahead: value } });
                reload();
              }} />
          )}
        </>
      )}

      <Advanced label={t("settings.advanced")}>
        <label className="panel__choice">
          <input type="checkbox" checked={data.keep_partial_on_cancel}
                 onChange={() => void write({ keep_partial_on_cancel: !data.keep_partial_on_cancel })} />
          <span>
            <span className="panel__choiceTitle">{t("settings.downloads.keepPartial")}</span>
            <span className="panel__choiceHelp">{t("settings.downloads.keepPartialHelp")}</span>
          </span>
        </label>

        <fieldset className="panel__group" role="radiogroup" aria-label={t("settings.downloads.method")}>
          <legend>{t("settings.downloads.method")}</legend>
          <label className="panel__choice">
            <input type="radio" name="method" value="" checked={data.extraction.method === null}
                   onChange={() => void write({ extraction: { method: null } })} />
            <span>{t("settings.downloads.method.auto")}</span>
          </label>
          {METHODS.map((method) => (
            <label key={method} className="panel__choice">
              <input type="radio" name="method" value={method} checked={data.extraction.method === method}
                     onChange={() => void write({ extraction: { method } })} />
              <span>{t(`settings.downloads.method.${method}` as StringKey)}</span>
            </label>
          ))}
        </fieldset>

        <fieldset className="panel__group" role="radiogroup" aria-label={t("settings.downloads.fallback")}>
          <legend>{t("settings.downloads.fallback")}</legend>
          {MODES.map((mode) => (
            <label key={mode} className="panel__choice">
              <input type="radio" name="fallback" value={mode} checked={data.extraction.mode === mode}
                     onChange={() => void write({ extraction: { mode } })} />
              <span>
                <span className="panel__choiceTitle">{t(`settings.downloads.fallback.${mode}` as StringKey)}</span>
                <span className="panel__choiceHelp">
                  {t(`settings.downloads.fallback.${mode}Help` as StringKey)}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      </Advanced>
    </section>
  );
}
