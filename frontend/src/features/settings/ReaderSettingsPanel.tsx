import { useRef, useState } from "react";

import { ApiError, api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";
import { DEFAULT_SETTINGS, loadSettings, saveSettings } from "@/features/reader/settings";
import type { ReaderSettings } from "@/features/reader/settings";
import { NumberSetting } from "./NumberSetting";
import { Advanced } from "./Advanced";

type LibraryReader = {
  auto_mark_read_threshold: number;
  smart_controls_hide_after_ms: number;
  remember_per_work: boolean;
  preload_next: number;
  preload_previous: number;
};

const MODES = ["long_strip", "single", "double"] as const;
const DIRECTIONS = ["ltr", "rtl", "vertical"] as const;
const FITS = ["smart", "width", "height", "original"] as const;
const BACKGROUNDS = ["black", "dark", "white"] as const;

/**
 * Reader settings (Master §32.14, §45).
 *
 * The normal ones first — how a work is read — then the technical ones behind Advanced: preload,
 * the auto-read threshold, whether a work remembers its own settings. The defaults for how pages are
 * shown live with the reader; the numbers the engine acts on live in the library (§42/D2).
 */
export function ReaderSettingsPanel() {
  const { t } = useI18n();
  const { data: loaded, error, reload } = useResource<LibraryReader>("/api/reader/settings");
  const [reader, setReader] = useState<ReaderSettings>(() => loadSettings(null, null) ?? DEFAULT_SETTINGS);

  const [saved, setSaved] = useState<LibraryReader | null>(null);
  const library = saved ?? loaded;
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const pending = useRef(false);

  const change = (update: Partial<ReaderSettings>) => {
    const merged = { ...reader, ...update };
    setReader(merged);
    saveSettings(null, merged);          // the global default, which a work may still override (§26.17)
  };

  const write = async (body: Record<string, number | boolean>) => {
    if (pending.current) return;
    pending.current = true;
    setSaving(true);
    setProblem(null);
    try {
      setSaved(await api.post<LibraryReader>("/api/reader/settings", body));
    } finally {
      pending.current = false;
      setSaving(false);
    }
  };

  const choice = <T extends string>(label: StringKey, name: string, values: readonly T[], current: T,
                                    apply: (value: T) => Partial<ReaderSettings>) => (
    <fieldset className="panel__group" role="radiogroup" aria-label={t(label)}>
      <legend>{t(label)}</legend>
      {values.map((value) => (
        <label key={value} className="panel__choice">
          <input type="radio" name={name} value={value} checked={current === value}
                 onChange={() => change(apply(value))} />
          <span>{t(`reader.${name}.${value}` as StringKey)}</span>
        </label>
      ))}
    </fieldset>
  );

  return (
    <section className="paper">
      <h2 className="display">{t("settings.reader")}</h2>
      <p className="firstrun__lede">{t("settings.reader.help")}</p>

      {choice("reader.mode", "mode", MODES, reader.mode, (mode) => ({ mode }))}
      {choice("reader.direction", "direction", DIRECTIONS, reader.direction, (direction) => ({ direction }))}
      {choice("reader.fit", "fit", FITS, reader.fit, (fit) => ({ fit }))}
      {choice("reader.background", "background", BACKGROUNDS, reader.background, (background) => ({ background }))}

      <NumberSetting label={t("settings.reader.gap")} value={reader.gap} min={0} max={64}
        onSave={gap => change({ gap })} />

      <label className="panel__choice">
        <input type="checkbox" checked={reader.coverAlone}
               onChange={() => change({ coverAlone: !reader.coverAlone })} />
        <span>{t("reader.coverAlone")}</span>
      </label>

      <Advanced label={t("settings.reader")}>
        {problem && <p className="notice notice--problem" role="alert">{problem}</p>}
        {library === null ? error ? <div>
          <p role="alert">{error === "offline" ? t("state.offline") : error}</p>
          <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button>
        </div> : <p>{t("state.loading")}</p> : (
          <>
            <NumberSetting label={t("settings.reader.preloadNext")} min={1} max={50}
              value={library.preload_next} disabled={saving} onSave={value => write({ preload_next: value })} />
            <NumberSetting label={t("settings.reader.preloadPrevious")} min={0} max={50}
              value={library.preload_previous} disabled={saving} onSave={value => write({ preload_previous: value })} />
            <NumberSetting label={t("settings.reader.threshold")} min={50} max={100}
              value={Math.round(library.auto_mark_read_threshold * 100)} disabled={saving}
              onSave={value => write({ auto_mark_read_threshold: value / 100 })} />
            <label className="panel__choice">
              <input type="checkbox" checked={library.remember_per_work} disabled={saving}
                     onChange={() => void write({ remember_per_work: !library.remember_per_work }).catch(error => {
                       setProblem(t("settings.notSaved", { message: error instanceof ApiError ? error.message : t("state.offline") }));
                     })} />
              <span>{t("settings.reader.rememberPerWork")}</span>
            </label>
          </>
        )}
      </Advanced>
    </section>
  );
}
