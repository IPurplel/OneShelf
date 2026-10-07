import { useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

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
import { handleTabKeys } from "@/components/tabKeyboard";

type Category = "general" | "reader" | "downloads" | "storage" | "sources" | "notifications" | "backup"
  | "remote" | "advanced" | "developer";

const CATEGORIES: Category[] = ["general", "reader", "downloads", "storage", "sources", "notifications", "backup",
                                "remote", "advanced", "developer"];

/** Settings (Master §32.14): a readable document — categories beside the panel, nothing shouted. */
export function SettingsScreen() {
  const { t, language, direction, setLanguage } = useI18n();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const section = pathname.split("/")[2];
  const category: Category = CATEGORIES.includes(section as Category) ? section as Category : "general";
  const navRef = useRef<HTMLDivElement>(null);
  const [navOverflow, setNavOverflow] = useState(false);

  useLayoutEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    let live = true;
    const reveal = () => {
      if (!live) return;
      setNavOverflow(nav.scrollWidth > nav.clientWidth + 1);
      nav.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView?.({ block: "nearest", inline: "center" });
    };
    reveal();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(reveal);
    observer?.observe(nav);
    window.addEventListener("resize", reveal);
    void document.fonts?.ready.then(reveal);
    return () => { live = false; observer?.disconnect(); window.removeEventListener("resize", reveal); };
  }, [category, language]);

  const scrollCategories = (step: -1 | 1) => {
    const nav = navRef.current;
    if (!nav) return;
    nav.scrollBy({ left: step * (direction === "rtl" ? -1 : 1) * nav.clientWidth * 0.75, behavior: "smooth" });
  };

  return (
    <section className="screen settings">
      <h1 className="screen__title">{t("settings.title")}</h1>

      <div className="settings__layout">
        <div className="settings__navRail">
          {navOverflow && <button type="button" className="settings__navStep"
                                  aria-label={t("settings.previousCategories")}
                                  onClick={() => scrollCategories(-1)}>
            <span aria-hidden="true">{direction === "rtl" ? "›" : "‹"}</span>
          </button>}
          <div ref={navRef} className={`settings__nav${navOverflow ? " settings__nav--overflow" : ""}`}
                role="tablist" aria-label={t("settings.categories")}
                aria-orientation={navOverflow ? "horizontal" : "vertical"} onKeyDown={handleTabKeys}>
            {CATEGORIES.map((candidate) => (
              <button key={candidate} type="button" role="tab" className="settings__tab"
                      id={`settings-tab-${candidate}`} aria-controls="settings-tabpanel"
                      aria-selected={category === candidate}
                      tabIndex={category === candidate ? 0 : -1}
                      onClick={() => void navigate(`/settings/${candidate}`)}>
                {t(`settings.${candidate}` as StringKey)}
              </button>
            ))}
          </div>
          {navOverflow && <button type="button" className="settings__navStep"
                                  aria-label={t("settings.nextCategories")}
                                  onClick={() => scrollCategories(1)}>
            <span aria-hidden="true">{direction === "rtl" ? "‹" : "›"}</span>
          </button>}
        </div>

        <div className="settings__panel" role="tabpanel" id="settings-tabpanel"
             aria-labelledby={`settings-tab-${category}`} tabIndex={0}>
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
