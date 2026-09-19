import { useState } from "react";

import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";
import { DEFAULT_SETTINGS, loadSettings, saveSettings } from "@/features/reader/settings";
import type { ReaderSettings } from "@/features/reader/settings";
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
  const { data: library, reload } = useResource<LibraryReader>("/api/reader/settings");
  const [reader, setReader] = useState<ReaderSettings>(() => loadSettings(null, null) ?? DEFAULT_SETTINGS);

  const change = (update: Partial<ReaderSettings>) => {
    const merged = { ...reader, ...update };
    setReader(merged);
    saveSettings(null, merged);          // the global default, which a work may still override (§26.17)
  };

  const write = async (body: Record<string, number | boolean>) => {
    try {
      await api.post("/api/reader/settings", body);
    } finally {
      reload();
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

      <label className="field__label">
        {t("settings.reader.gap")}
        <input type="number" className="field" min={0} max={64} value={reader.gap}
               onChange={(event) => change({ gap: Number(event.target.value) })} />
      </label>

      <label className="panel__choice">
        <input type="checkbox" checked={reader.coverAlone}
               onChange={() => change({ coverAlone: !reader.coverAlone })} />
        <span>{t("reader.coverAlone")}</span>
      </label>

      <Advanced label={t("settings.advanced")}>
        {library === null ? <p>{t("state.loading")}</p> : (
          <>
            <label className="field__label">
              {t("settings.reader.preloadNext")}
              <input type="number" className="field" min={1} max={50} defaultValue={library.preload_next}
                     onBlur={(event) => {
                       const value = Number(event.target.value);
                       if (value !== library.preload_next) void write({ preload_next: value });
                     }} />
            </label>
            <label className="field__label">
              {t("settings.reader.preloadPrevious")}
              <input type="number" className="field" min={0} max={50} defaultValue={library.preload_previous}
                     onBlur={(event) => {
                       const value = Number(event.target.value);
                       if (value !== library.preload_previous) void write({ preload_previous: value });
                     }} />
            </label>
            <label className="field__label">
              {t("settings.reader.threshold")}
              <input type="number" className="field" min={50} max={100}
                     defaultValue={Math.round(library.auto_mark_read_threshold * 100)}
                     onBlur={(event) => {
                       const value = Number(event.target.value) / 100;
                       if (value !== library.auto_mark_read_threshold) {
                         void write({ auto_mark_read_threshold: value });
                       }
                     }} />
            </label>
            <label className="panel__choice">
              <input type="checkbox" checked={library.remember_per_work}
                     onChange={() => void write({ remember_per_work: !library.remember_per_work })} />
              <span>{t("settings.reader.rememberPerWork")}</span>
            </label>
          </>
        )}
      </Advanced>
    </section>
  );
}
