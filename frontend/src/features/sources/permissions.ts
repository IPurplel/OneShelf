import type { StringKey } from "@/i18n/strings";

export type Translate = (key: StringKey, values?: Record<string, string | number>) => string;

/**
 * A permission read back in the reader's own words (Master §11.4). Callers keep the token beside it,
 * so a careful reader can still see exactly what was granted.
 */
export function explain(permission: string, t: Translate): string {
  const [group, kind = "", rest] = permission.split(":");
  const domain = rest ?? kind;
  if (group === "network" && kind === "domain") return t("install.perm.domain", { domain });
  if (group === "network" && kind === "cdn") return t("install.perm.cdn", { domain });
  if (group === "network" && kind === "http") return t("install.perm.http");
  if (group === "browser" && kind === "login") return t("install.perm.login");
  if (group === "browser") return t("install.perm.browser", { what: kind });
  if (group === "session" && kind === "required") return t("install.perm.sessionRequired", { what: domain });
  if (group === "session") return t("install.perm.sessionOptional", { what: domain });
  return permission;
}
