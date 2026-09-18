import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";

/** A screen that exists in navigation but is still being built. It never shows invented content. */
export function Placeholder({ titleKey }: { titleKey: StringKey }) {
  const { t } = useI18n();
  return (
    <section className="screen">
      <h1 className="screen__title">{t(titleKey)}</h1>
    </section>
  );
}
