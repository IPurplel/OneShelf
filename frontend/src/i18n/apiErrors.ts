import { ApiError } from "@/api/client";
import type { Language, StringKey } from "./strings";

/**
 * A failed request in words a reader can act on: what happened, what OneShelf kept safe, what to do.
 * Each stable error code the interface can receive has its own sentence in both languages.
 */
const MESSAGES: Record<string, StringKey> = {
  BACKUP_FAILED: "error.backupFailed",
  BACKUP_UNREADABLE: "error.backupUnreadable",
  RESTORE_REFUSED: "error.restoreRefused",
  ROOT_REJECTED: "error.storageRejected",
  STORAGE_REJECTED: "error.storageRejected",
  EXPORT_REFUSED: "error.exportRefused",
  IMPORT_REJECTED: "error.importRejected",
  UNSUPPORTED_FILE: "error.unsupportedFile",
  INSTALL_REJECTED: "error.sourceRejected",
  DOWNLOAD_REQUIRED: "error.downloadRequired",
  SOURCE_FAILED: "error.code.sourceFailed",
  RATE_LIMITED: "error.code.rateLimited",
  SESSION_REQUIRED: "error.code.sessionRequired",
  SOURCE_UNAVAILABLE: "error.code.sourceUnavailable",
  UNIT_NOT_FOUND: "error.code.unitNotFound",
  WORK_NOT_FOUND: "error.code.workNotFound",
  TRACK_NOT_FOUND: "error.code.trackNotFound",
  LISTING_NOT_FOUND: "error.code.listingNotFound",
  UNDO_EXPIRED: "error.code.undoExpired",
  NOT_A_DIRECTORY: "error.code.notADirectory",
  TAG_EXISTS: "error.code.tagExists",
  NO_STORAGE_LOCATION: "error.code.noStorage",
  CANNOT_ENQUEUE: "error.code.cannotEnqueue",
  FILE_NOT_AVAILABLE: "error.code.fileNotAvailable",
  PAGES_NOT_AVAILABLE: "error.code.pagesNotAvailable",
  PAGE_NOT_FOUND: "error.code.pagesNotAvailable",
  TEXT_NOT_AVAILABLE: "error.code.pagesNotAvailable",
  STALE_PROGRESS: "error.code.staleProgress",
  FILE_TOO_LARGE: "error.code.fileTooLarge",
  PACKAGE_TOO_LARGE: "error.code.fileTooLarge",
  INVALID_PACKAGE: "error.sourceRejected",
  REVIEW_REJECTED: "error.sourceRejected",
  REGISTRY_UNAVAILABLE: "error.code.registryUnavailable",
  REGISTRY_NOT_CONFIGURED: "error.code.registryUnavailable",
  UNSUPPORTED_URL: "error.code.unsupportedUrl",
  INVALID_NETWORK: "error.code.invalidNetwork",
  INVALID_HOSTNAME: "error.code.invalidHostname",
  SIGN_IN_FAILED: "error.code.signInFailed",
  PASSKEY_ERROR: "error.code.signInFailed",
  LAN_REQUIRED: "error.code.lanRequired",
  REGISTRATION_NOT_AUTHORIZED: "error.code.lanRequired",
  LOGIN_UNAVAILABLE: "error.code.loginUnavailable",
  NOT_FOLLOWED: "error.code.notFollowed",
  PERMANENT_DOWNLOAD_NOTICE_REQUIRED: "error.code.downloadNotice",
  MIGRATION_REFUSED: "error.code.migrationRefused",
  REMAP_REFUSED: "error.code.migrationRefused",
};

/**
 * Codes whose English server text is engine wording ("parser_failure: …", "No reading unit by that id."):
 * these read from the interface's own sentence in English too. Every other English error keeps the
 * server's message, which is already written for a person and often names the exact item.
 */
const ENGLISH_TOO = new Set(["SOURCE_FAILED", "RATE_LIMITED", "SESSION_REQUIRED", "SOURCE_UNAVAILABLE",
  "UNIT_NOT_FOUND", "UNDO_EXPIRED", "NOT_A_DIRECTORY", "TAG_EXISTS", "STALE_PROGRESS"]);

export function apiErrorText(error: unknown, language: Language,
                             t: (key: StringKey) => string): string {
  if (!(error instanceof ApiError)) return t("state.offline");
  const key = MESSAGES[error.code];
  if (language === "en") return key && ENGLISH_TOO.has(error.code) ? t(key) : error.message;
  return t(key ?? "state.requestFailed");
}
