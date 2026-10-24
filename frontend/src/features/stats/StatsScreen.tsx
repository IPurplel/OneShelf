import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import { LoadingState } from "@/components/LoadingState";
import type { StringKey } from "@/i18n/strings";

type StatsResponse = {
  library: { works: number; shelf: number; units: number; favorites: number; follows: number };
  reading: { unread: number; partial: number; read: number; completion_rate: number };
  downloads: { completed: number; total_bytes: number; total_pages: number };
  content_types: { type: string; count: number }[];
  activity: { day: string; count: number }[];
};

function formatBytes(bytes: number, language: string): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** i;
  return `${new Intl.NumberFormat(language, { maximumFractionDigits: 1 }).format(value)} ${units[i]}`;
}

export function StatsScreen() {
  const { t, language } = useI18n();
  const { data, error, loading, reload } = useResource<StatsResponse>("/api/stats");
  const fmt = (n: number) => new Intl.NumberFormat(language).format(n);

  return (
    <section className="screen">
      <h1 className="screen__title">{t("stats.title")}</h1>
      <p className="screen__subtitle">{t("stats.subtitle")}</p>

      {error !== null && (
        <>
          <p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
          <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button>
        </>
      )}
      {loading && <LoadingState />}

      {data && (
        <div className="stats">
          <div className="stats__cards" role="list" aria-label={t("stats.library")}>
            <StatCard label={t("stats.works")} value={fmt(data.library.works)} />
            <StatCard label={t("stats.shelf")} value={fmt(data.library.shelf)} />
            <StatCard label={t("stats.units")} value={fmt(data.library.units)} />
            <StatCard label={t("stats.favorites")} value={fmt(data.library.favorites)} />
            <StatCard label={t("stats.follows")} value={fmt(data.library.follows)} />
          </div>

          <div className="stats__section">
            <h2 className="stats__heading">{t("stats.readingProgress")}</h2>
            <div className="stats__bar-group">
              <ProgressRow label={t("stats.read")} count={data.reading.read}
                total={data.reading.read + data.reading.partial + data.reading.unread} color="var(--olive-600)" fmt={fmt} />
              <ProgressRow label={t("stats.partial")} count={data.reading.partial}
                total={data.reading.read + data.reading.partial + data.reading.unread} color="var(--wood-500)" fmt={fmt} />
              <ProgressRow label={t("stats.unread")} count={data.reading.unread}
                total={data.reading.read + data.reading.partial + data.reading.unread} color="var(--ink-300)" fmt={fmt} />
            </div>
            <p className="stats__caption">
              {t("stats.completionRate", { rate: `${Math.round(data.reading.completion_rate * 100)}%` })}
            </p>
          </div>

          {data.content_types.length > 0 && (
            <div className="stats__section">
              <h2 className="stats__heading">{t("stats.contentTypes")}</h2>
              <div className="stats__types">
                {data.content_types.map(({ type, count }) => (
                  <div key={type} className="stats__type" role="listitem">
                    <span className="stats__typeLabel">{t(`stats.type.${type}` as StringKey)}</span>
                    <span className="stats__typeCount">{fmt(count)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="stats__section">
            <h2 className="stats__heading">{t("stats.downloads")}</h2>
            <div className="stats__cards stats__cards--compact" role="list">
              <StatCard label={t("stats.filesDownloaded")} value={fmt(data.downloads.completed)} />
              <StatCard label={t("stats.totalSize")} value={formatBytes(data.downloads.total_bytes, language)} />
              <StatCard label={t("stats.totalPages")} value={fmt(data.downloads.total_pages)} />
            </div>
          </div>

          {data.activity.length > 0 && (
            <div className="stats__section">
              <h2 className="stats__heading">{t("stats.activity")}</h2>
              <ActivityChart activity={data.activity} language={language} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="stats__card" role="listitem">
      <span className="stats__cardValue">{value}</span>
      <span className="stats__cardLabel">{label}</span>
    </div>
  );
}

function ProgressRow({ label, count, total, color, fmt }: {
  label: string; count: number; total: number; color: string;
  fmt: (n: number) => string;
}) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <div className="stats__barRow">
      <span className="stats__barLabel">{label}</span>
      <div className="stats__barTrack">
        <div className="stats__barFill" style={{ inlineSize: `${pct}%`, background: color }} />
      </div>
      <span className="stats__barCount">{fmt(count)}</span>
    </div>
  );
}

function ActivityChart({ activity, language }: { activity: StatsResponse["activity"]; language: string }) {
  const max = Math.max(...activity.map((d) => d.count), 1);
  const dateFormat = new Intl.DateTimeFormat(language, { month: "short", day: "numeric" });
  return (
    <div className="stats__chart" role="img" aria-label="Reading activity last 30 days">
      {activity.map(({ day, count }) => (
        <div key={day} className="stats__chartCol" title={`${dateFormat.format(new Date(day + "T00:00:00"))}: ${count}`}>
          <div className="stats__chartBar" style={{ blockSize: `${(count / max) * 100}%` }} />
          {activity.length <= 14 && (
            <span className="stats__chartDay">{dateFormat.format(new Date(day + "T00:00:00"))}</span>
          )}
        </div>
      ))}
    </div>
  );
}
