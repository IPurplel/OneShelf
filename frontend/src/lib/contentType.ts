import type { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";

const CONTENT_TYPES = ["manga", "manhwa", "manhua", "comic", "book", "paper"];

/** A content type in the reader's language; one the interface has no word for is shown as it came. */
export function typeLabel(value: string, t: ReturnType<typeof useI18n>["t"]): string {
  return CONTENT_TYPES.includes(value) ? t(`work.type.${value}` as StringKey) : value.replaceAll("_", " ");
}
