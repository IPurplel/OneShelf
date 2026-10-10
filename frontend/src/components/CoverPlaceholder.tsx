import { useI18n } from "@/i18n/i18n";

/** A typographic cover for works without artwork. The surrounding card or heading names the work. */
export function CoverPlaceholder({ title, className = "" }: { title: string; className?: string }) {
  const { t } = useI18n();
  let hash = 5381;
  for (const character of title) hash = ((hash * 33) ^ (character.codePointAt(0) ?? 0)) >>> 0;
  const tone = ["forest", "olive", "wood", "linen"][hash % 4];

  return (
    <span className={`cover-placeholder ${className}`} data-tone={tone} data-title={title} aria-hidden="true">
      <span className="cover-placeholder__initial">{title.slice(0, 1)}</span>
      <span className="cover-placeholder__imprint">{t("app.name")}</span>
      <span className="cover-placeholder__rule" />
    </span>
  );
}
