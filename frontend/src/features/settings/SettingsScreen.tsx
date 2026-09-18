import { useState } from "react";

import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";

type Category = "general" | "reader" | "downloads" | "storage" | "sources" | "notifications" | "backup"
  | "remote" | "advanced" | "developer";

const CATEGORIES: Category[] = ["general", "reader", "downloads", "storage", "sources", "notifications", "backup",
                                "remote", "advanced", "developer"];

type AuthState = {
  canonical_hostname: string | null;
  remote_enabled: boolean;
  passkeys: { credential_id: string; label: string }[];
  sessions: { id: string; label: string }[];
  network: { trusted_networks: string[]; trusted_proxies: string[]; gateway_warning: { message: string } | null };
};

type Root = { id: string; name: string; path: string; available: boolean; free: number; total: number;
              reserve: number; is_default: boolean; state: string };

/** Settings (Master §32.14): a readable document — categories beside the panel, nothing shouted. */
export function SettingsScreen() {
  const { t, language, setLanguage } = useI18n();
  const [category, setCategory] = useState<Category>("general");
  const { data: auth } = useResource<AuthState>("/api/auth/state");
  const { data: storage } = useResource<{ roots: Root[] }>("/api/storage");

  return (
    <section className="screen settings">
      <h1 className="screen__title">{t("settings.title")}</h1>

      <div className="settings__layout">
        <div className="settings__nav" role="tablist" aria-label={t("settings.categories")} aria-orientation="vertical">
          {CATEGORIES.map((candidate) => (
            <button key={candidate} type="button" role="tab" className="settings__tab"
                    aria-selected={category === candidate} onClick={() => setCategory(candidate)}>
              {t(`settings.${candidate}` as StringKey)}
            </button>
          ))}
        </div>

        <div className="settings__panel" role="tabpanel" aria-label={t(`settings.${category}` as StringKey)}>
          {category === "general" && (
            <section className="paper">
              <h2 className="display">{t("settings.language")}</h2>
              <div className="toolbar__tabs">
                {(["en", "ar"] as const).map((code) => (
                  <button key={code} type="button" className="chip" aria-pressed={language === code}
                          onClick={() => setLanguage(code)}>
                    {code === "en" ? "English" : "العربية"}
                  </button>
                ))}
              </div>
            </section>
          )}

          {category === "storage" && (
            <section className="paper">
              <ul className="cards">
                {(storage?.roots ?? []).map((root) => (
                  <li key={root.id} className="cards__row">
                    <span className="cards__name display">{root.name}</span>
                    <span className="cards__meta">{root.path}</span>
                    <span className="cards__meta">
                      {t("settings.free", { free: bytes(root.free), total: bytes(root.total) })}
                    </span>
                    <span className="cards__meta">{t("settings.reserve", { reserve: bytes(root.reserve) })}</span>
                    {root.is_default && <span className="cards__ok">{t("settings.default")}</span>}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {category === "remote" && (
            <section className="paper">
              {auth?.remote_enabled ? (
                <dl className="details">
                  <dt>{t("settings.remote.host")}</dt><dd>{auth.canonical_hostname}</dd>
                  <dt>{t("settings.remote.passkeys")}</dt><dd>{auth.passkeys.length}</dd>
                  <dt>{t("settings.remote.sessions")}</dt><dd>{auth.sessions.length}</dd>
                </dl>
              ) : (
                <p>{t("settings.remote.none")}</p>
              )}
              {auth?.network.gateway_warning && (
                <p className="notice notice--problem">{auth.network.gateway_warning.message}</p>
              )}
            </section>
          )}

          {category === "developer" && (
            <section className="paper">
              <h2 className="display">{t("settings.developer.generator")}</h2>
              <p>{t("settings.developer.body")}</p>
            </section>
          )}

          {!["general", "storage", "remote", "developer"].includes(category) && (
            <section className="paper"><p>{t("settings.soon")}</p></section>
          )}
        </div>
      </div>
    </section>
  );
}

function bytes(value: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}
