import { useState } from "react";

import { useResource } from "@/api/useApi";
import { StoragePanel } from "@/features/storage/StoragePanel";
import { ImportPanel } from "@/features/storage/ImportPanel";
import { BackupPanel } from "@/features/backup/BackupPanel";
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

/** Settings (Master §32.14): a readable document — categories beside the panel, nothing shouted. */
export function SettingsScreen() {
  const { t, language, setLanguage } = useI18n();
  const [category, setCategory] = useState<Category>("general");
  const { data: auth } = useResource<AuthState>("/api/auth/state");

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
            <>
              <StoragePanel />
              <ImportPanel />
            </>
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

          {category === "backup" && <BackupPanel />}

          {category === "developer" && (
            <section className="paper">
              <h2 className="display">{t("settings.developer.generator")}</h2>
              <p>{t("settings.developer.body")}</p>
            </section>
          )}

          {!["general", "storage", "remote", "developer", "backup"].includes(category) && (
            <section className="paper"><p>{t("settings.soon")}</p></section>
          )}
        </div>
      </div>
    </section>
  );
}

