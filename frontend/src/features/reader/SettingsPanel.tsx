import { useI18n } from "@/i18n/i18n";
import { Drawer } from "@/components/Drawer";
import type { ReaderDirection, ReaderFit, ReaderMode, ReaderSettings } from "./settings";

const MODES: ReaderMode[] = ["long_strip", "single", "double"];
const DIRECTIONS: ReaderDirection[] = ["ltr", "rtl", "vertical"];
const FITS: ReaderFit[] = ["smart", "width", "height", "original"];

/** Reader settings (Master §26.17): the normal ones here, advanced ones behind progressive disclosure. */
export function SettingsPanel({ settings, onChange, onClose }: {
  settings: ReaderSettings;
  onChange: (update: Partial<ReaderSettings>) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <Drawer title={t("reader.settings")} onClose={onClose}>
      <fieldset className="panel__group" role="radiogroup" aria-label={t("reader.mode")}>
        <legend>{t("reader.mode")}</legend>
        {MODES.map((mode) => (
          <label key={mode} className="panel__choice">
            <input type="radio" name="mode" value={mode} checked={settings.mode === mode}
                   onChange={() => onChange({ mode })} />
            <span>{t(`reader.mode.${mode}` as const)}</span>
          </label>
        ))}
      </fieldset>

      <fieldset className="panel__group" role="radiogroup" aria-label={t("reader.direction")}>
        <legend>{t("reader.direction")}</legend>
        {DIRECTIONS.map((direction) => (
          <label key={direction} className="panel__choice">
            <input type="radio" name="direction" value={direction} checked={settings.direction === direction}
                   onChange={() => onChange({ direction })} />
            <span>{t(`reader.direction.${direction}` as const)}</span>
          </label>
        ))}
      </fieldset>

      <fieldset className="panel__group" role="radiogroup" aria-label={t("reader.fit")}>
        <legend>{t("reader.fit")}</legend>
        {FITS.map((fit) => (
          <label key={fit} className="panel__choice">
            <input type="radio" name="fit" value={fit} checked={settings.fit === fit}
                   onChange={() => onChange({ fit })} />
            <span>{t(`reader.fit.${fit}` as const)}</span>
          </label>
        ))}
      </fieldset>

      <fieldset className="panel__group" role="radiogroup" aria-label={t("reader.background")}>
        <legend>{t("reader.background")}</legend>
        {(["black", "dark", "white"] as const).map((background) => (
          <label key={background} className="panel__choice">
            <input type="radio" name="background" value={background} checked={settings.background === background}
                   onChange={() => onChange({ background })} />
            <span>{t(`reader.background.${background}` as const)}</span>
          </label>
        ))}
      </fieldset>
    </Drawer>
  );
}
