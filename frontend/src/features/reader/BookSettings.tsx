import { Drawer } from "@/components/Drawer";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";
import type { BookFont, BookMargins, BookSize, BookSpacing, BookTheme, ReaderSettings } from "./settings";

const FONTS: BookFont[] = ["serif", "sans"];
const SIZES: BookSize[] = ["smaller", "normal", "larger", "largest"];
const SPACING: BookSpacing[] = ["tight", "normal", "loose"];
const MARGINS: BookMargins[] = ["narrow", "normal", "wide"];
const THEMES: BookTheme[] = ["paper", "sepia", "dark"];

/**
 * Reading comfort for a book (Master §26.22a).
 *
 * Type, size, spacing, margins and theme — the settings a long read needs. None of them reach the book:
 * they are applied by OneShelf's own stylesheet inside a frame that keeps its empty sandbox and its own
 * CSP (§27, ledger K3). They follow §26.17's precedence like every other reader setting, so a book
 * remembers how it is read.
 */
export function BookSettings({ settings, onChange, onClose }: {
  settings: ReaderSettings;
  onChange: (update: Partial<ReaderSettings>) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();

  const group = <T extends string>(label: StringKey, name: string, values: readonly T[], current: T,
                                   apply: (value: T) => Partial<ReaderSettings>) => (
    <fieldset className="panel__group" role="radiogroup" aria-label={t(label)}>
      <legend>{t(label)}</legend>
      {values.map((value) => (
        <label key={value} className="panel__choice">
          <input type="radio" name={name} value={value} checked={current === value}
                 onChange={() => onChange(apply(value))} />
          <span>{t(`book.${name}.${value}` as StringKey)}</span>
        </label>
      ))}
    </fieldset>
  );

  return (
    <Drawer title={t("book.comfort")} onClose={onClose}>
      {group("book.font", "font", FONTS, settings.bookFont, (bookFont) => ({ bookFont }))}
      {group("book.size", "size", SIZES, settings.bookSize, (bookSize) => ({ bookSize }))}
      {group("book.spacing", "spacing", SPACING, settings.bookSpacing, (bookSpacing) => ({ bookSpacing }))}
      {group("book.margins", "margins", MARGINS, settings.bookMargins, (bookMargins) => ({ bookMargins }))}
      {group("book.theme", "theme", THEMES, settings.bookTheme, (bookTheme) => ({ bookTheme }))}
    </Drawer>
  );
}
