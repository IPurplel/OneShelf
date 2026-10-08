import { ApiError } from "@/api/client";
import type { Language, StringKey } from "./strings";

const ARABIC_ERRORS: Record<string, StringKey> = {
  BACKUP_FAILED: "error.backupFailed",
  BACKUP_UNREADABLE: "error.backupUnreadable",
  RESTORE_REFUSED: "error.restoreRefused",
  ROOT_REJECTED: "error.storageRejected",
  EXPORT_REFUSED: "error.exportRefused",
  IMPORT_REJECTED: "error.importRejected",
  UNSUPPORTED_FILE: "error.unsupportedFile",
  INSTALL_REJECTED: "error.sourceRejected",
};

/** Service prose is English; use stable codes for supported Arabic messages and a safe generic fallback. */
export function apiErrorText(error: unknown, language: Language,
                             t: (key: StringKey) => string): string {
  if (!(error instanceof ApiError)) return t("state.offline");
  if (language === "en") return error.message;
  return t(ARABIC_ERRORS[error.code] ?? "state.requestFailed");
}
