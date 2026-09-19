import { useState } from "react";

import { StoragePanel } from "@/features/storage/StoragePanel";
import { ImportPanel } from "@/features/storage/ImportPanel";
import { BackupPanel } from "@/features/backup/BackupPanel";
import { RemotePanel } from "@/features/remote/RemotePanel";
import { GeneratorPanel } from "@/features/generator/GeneratorPanel";
import { AdvancedSettingsPanel } from "./AdvancedSettingsPanel";
import { DownloadSettingsPanel } from "./DownloadSettingsPanel";
import { NotificationSettingsPanel } from "./NotificationSettingsPanel";
import { ReaderSettingsPanel } from "./ReaderSettingsPanel";
import { SourceSettingsPanel } from "./SourceSettingsPanel";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";

type Category = "general" | "reader" | "downloads" | "storage" | "sources" | "notifications" | "backup"
  | "remote" | "advanced" | "developer";

const CATEGORIES: Category[] = ["general", "reader", "downloads", "storage", "sources", "notifications", "backup",
                                "remote", "advanced", "developer"];

/** Settings (Master §32.14): a readable document — categories beside the panel, nothing shouted. */
export function SettingsScreen() {
  const { t, language, setLanguage } = useI18n();
  const [category, setCategory] = useState<Category>("general");

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

          {category === "reader" && <ReaderSettingsPanel />}

          {category === "downloads" && <DownloadSettingsPanel />}

          {category === "sources" && <SourceSettingsPanel />}

          {category === "notifications" && <NotificationSettingsPanel />}

          {category === "advanced" && <AdvancedSettingsPanel />}

          {category === "remote" && <RemotePanel />}

          {category === "backup" && <BackupPanel />}

          {category === "developer" && <GeneratorPanel />}


        </div>
      </div>
    </section>
  );
}

