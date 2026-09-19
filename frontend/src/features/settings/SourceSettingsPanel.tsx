import { Link } from "react-router-dom";

import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";
import { Advanced } from "./Advanced";

type Source = {
  id: string; name: string; state: string; version: string | null; trust_label: string;
  channel: string; capabilities: string[]; session_state: string;
};

/**
 * Source settings (Master §21, §32.12, §45; ledger A3).
 *
 * There is one place sources are managed, and it is the Sources screen — this panel holds preferences
 * and points there rather than keeping a second copy of the same state. Normal is what a reader needs
 * to know: what each source does and whether it is working. Versions, channels and trust labels are
 * technical, and sit behind Advanced.
 */
export function SourceSettingsPanel() {
  const { t } = useI18n();
  const { data } = useResource<{ sources: Source[] }>("/api/sources");
  const sources = data?.sources ?? [];

  return (
    <section className="paper">
      <h2 className="display">{t("settings.sources")}</h2>
      <p className="firstrun__lede">{t("settings.sources.help")}</p>

      {data !== null && sources.length === 0 && <p className="shelf__empty">{t("sources.empty")}</p>}

      <ul className="cards">
        {sources.map((source) => (
          <li key={source.id} className="cards__row">
            <span className="cards__name display">{source.name}</span>
            <span className="cards__meta">{source.capabilities.join(" · ")}</span>
            <span className={`cards__state cards__state--${source.state}`}>
              {t(`sources.state.${source.state}` as StringKey)}
            </span>
          </li>
        ))}
      </ul>

      <div className="firstrun__actions">
        <Link className="button" to="/sources">{t("settings.sources.manage")}</Link>
      </div>

      <Advanced label={t("settings.advanced")}>
        <p className="cards__meta">{t("settings.sources.advancedHelp")}</p>
        <ul className="cards">
          {sources.map((source) => (
            <li key={source.id} className="cards__row">
              <span className="cards__name">{source.id}</span>
              <span className="cards__meta">{source.version ?? "—"}</span>
              <span className="cards__meta">{source.trust_label}</span>
              <span className="cards__meta">{source.channel}</span>
            </li>
          ))}
        </ul>
      </Advanced>
    </section>
  );
}
