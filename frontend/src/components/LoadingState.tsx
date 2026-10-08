import { useI18n } from "@/i18n/i18n";

/** A consistent visible status while a screen's first answer is pending. */
export function LoadingState() {
  const { t } = useI18n();
  return <p className="notice loading-state" role="status">{t("state.loading")}</p>;
}
