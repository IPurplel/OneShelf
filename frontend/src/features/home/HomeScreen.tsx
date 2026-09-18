import { useI18n } from "@/i18n/i18n";

/** Home (Master §31, §32.3). Sections appear only when there is something real to show. */
export function HomeScreen() {
  const { t } = useI18n();
  return (
    <section className="screen">
      <h1 className="screen__title">{t("app.name")}</h1>
      <p className="screen__subtitle">{t("app.tagline")}</p>
    </section>
  );
}
