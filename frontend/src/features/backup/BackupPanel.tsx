import { useState } from "react";

import { ApiError, api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";
import { bytes } from "@/lib/format";

type Backup = {
  id: string; path: string; kind: "library" | "full"; created_at: string;
  verified_at: string | null; size_bytes: number; present: boolean;
};

type BackupsResponse = {
  backups: Backup[];
  due: boolean;
  location_warning: { same_device_as_library: boolean; message: string } | null;
};

type PluginRequirement = {
  id: string; version: string; installed: boolean; installed_version: string | null; new_permissions: string[];
};

type Preflight = {
  ok: boolean; compatible: boolean; kind: string; schema_version: number;
  counts: Record<string, number>; plugins: PluginRequirement[]; space_needed: number; issues: string[];
};

/**
 * Backup and Restore (Master §33, §32.15).
 *
 * Restore is a workflow, not a modal with a red button: the archive is checked, what it holds is read
 * out, the two modes are explained in words — Merge never moves reading progress backwards, Replace
 * takes a Safety Snapshot first — and only then can it run. An archive OneShelf cannot accept says why.
 */
export function BackupPanel() {
  const { t } = useI18n();
  const { data, reload } = useResource<BackupsResponse>("/api/backups");
  const [restoring, setRestoring] = useState<Backup | null>(null);
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [mode, setMode] = useState<"merge" | "replace">("merge");
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const backups = data?.backups ?? [];

  const makeBackup = async (kind: "library" | "full") => {
    setProblem(null);
    try {
      await api.post("/api/backups", { kind });
      setMessage(t("backup.made"));
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      reload();
    }
  };

  const openRestore = async (backup: Backup) => {
    setRestoring(backup);
    setPreflight(null);
    setProblem(null);
    setMode("merge");
    try {
      setPreflight(await api.post<Preflight>("/api/restore/preflight", { path: backup.path }));
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    }
  };

  const restore = async () => {
    if (restoring === null) return;
    try {
      await api.post("/api/restore", { path: restoring.path, mode });
      setMessage(t("backup.restored"));
      setRestoring(null);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      reload();
    }
  };

  return (
    <section className="paper">
      <h2 className="display">{t("backup.title")}</h2>

      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {message !== null && <p className="notice" role="status">{message}</p>}
      {data?.location_warning?.same_device_as_library && (
        <p className="notice notice--problem">{data.location_warning.message}</p>
      )}
      {data?.due && <p className="notice">{t("backup.due")}</p>}

      <ul className="cards">
        {backups.map((backup) => (
          <li key={backup.path} className="cards__row">
            <span className="cards__name display">{t(`backup.kind.${backup.kind}` as StringKey)}</span>
            <span className="cards__meta">{new Date(backup.created_at).toLocaleString()}</span>
            {backup.present ? (
              <>
                <span className="cards__meta">{bytes(backup.size_bytes)}</span>
                {backup.verified_at !== null && <span className="cards__ok">{t("backup.verified")}</span>}
                <button type="button" className="chip" onClick={() => void openRestore(backup)}>
                  {t("backup.restore")}
                </button>
              </>
            ) : (
              <span className="cards__warn">{t("backup.missing")}</span>
            )}
          </li>
        ))}
      </ul>

      {data !== null && backups.length === 0 && <p className="shelf__empty">{t("backup.none")}</p>}

      <div className="firstrun__actions">
        <button type="button" className="button button--primary" onClick={() => void makeBackup("library")}>
          {t("backup.makeLibrary")}
        </button>
        <button type="button" className="button" onClick={() => void makeBackup("full")}>
          {t("backup.makeFull")}
        </button>
      </div>

      {restoring !== null && (
        <div className="confirm confirm--wide" role="dialog" aria-modal="true" aria-label={t("backup.restoreTitle")}>
          <h2 className="display">{t("backup.restoreTitle")}</h2>

          {preflight === null && problem === null && <p>{t("state.loading")}</p>}

          {preflight !== null && (
            <>
              <section className="restore__step">
                <h3>{t("backup.holds")}</h3>
                <ul className="restore__counts">
                  {Object.entries(preflight.counts).map(([what, count]) => (
                    <li key={what}>{count} {what.replace(/_/g, " ")}</li>
                  ))}
                </ul>
              </section>

              {preflight.plugins.length > 0 && (
                <section className="restore__step">
                  <h3>{t("backup.sources")}</h3>
                  <ul className="restore__plugins">
                    {preflight.plugins.map((plugin) => (
                      <li key={plugin.id}>
                        <span>{plugin.id} {plugin.version}</span>
                        <span className="cards__meta">
                          {plugin.installed ? t("backup.installed") : t("backup.notInstalled")}
                        </span>
                        {plugin.new_permissions.length > 0 && (
                          <span className="cards__warn">{t("backup.newPermissions")}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                  <p className="cards__meta">{t("backup.pluginsNote")}</p>
                </section>
              )}

              {preflight.compatible ? (
                <section className="restore__step">
                  <fieldset className="panel__group" role="radiogroup" aria-label={t("backup.how")}>
                    <legend>{t("backup.how")}</legend>
                    {(["merge", "replace"] as const).map((candidate) => (
                      <label key={candidate} className="panel__choice">
                        <input type="radio" name="restore-mode" value={candidate} checked={mode === candidate}
                               onChange={() => setMode(candidate)} />
                        <span>
                          <span className="panel__choiceTitle">{t(`backup.mode.${candidate}` as StringKey)}</span>
                          <span className="panel__choiceHelp">{t(`backup.mode.${candidate}Help` as StringKey)}</span>
                        </span>
                      </label>
                    ))}
                  </fieldset>
                </section>
              ) : (
                <ul className="restore__issues">
                  {preflight.issues.map((issue) => <li key={issue} className="cards__warn">{issue}</li>)}
                </ul>
              )}
            </>
          )}

          <div className="confirm__actions">
            <button type="button" className="button" onClick={() => setRestoring(null)}>{t("common.cancel")}</button>
            {preflight?.compatible && (
              <button type="button" className="button button--primary" onClick={() => void restore()}>
                {t("backup.restore")}
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
