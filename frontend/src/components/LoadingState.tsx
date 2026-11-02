import { useI18n } from "@/i18n/i18n";

/**
 * A consistent visible status while a screen's first answer is pending. `shelf` and `rows` draw the shape
 * of what is coming — covers on a plank, or list rows — so the page does not jump when it arrives.
 */
export function LoadingState({ variant = "line" }: { variant?: "line" | "shelf" | "rows" }) {
  const { t } = useI18n();
  if (variant === "line") return <p className="notice loading-state" role="status">{t("state.loading")}</p>;
  return (
    <div className={`loading-state loading-state--skeleton skeleton skeleton--${variant}`} role="status">
      <span className="visually-hidden">{t("state.loading")}</span>
      {variant === "shelf" ? (
        <div className="skeleton__shelf" aria-hidden="true">
          {Array.from({ length: 6 }, (_, index) => <span key={index} className="skeleton__cover" />)}
        </div>
      ) : (
        Array.from({ length: 4 }, (_, index) => <span key={index} className="skeleton__row" aria-hidden="true" />)
      )}
    </div>
  );
}
