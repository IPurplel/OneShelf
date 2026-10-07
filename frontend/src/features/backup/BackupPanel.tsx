import { useRef, useState } from "react";

import { ApiError, api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { ModalSurface } from "@/components/ModalSurface";
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
const COUNT_KEYS = new Set(["works", "source_tracks", "reading_units", "assets", "shelf_entries", "follows",
  "reading_state", "work_mappings", "user_overrides", "settings", "reading_bookmarks", "reading_highlights"]);

/**
 * Backup and Restore (Master §33, §32.15).
 *
 * Restore is a workflow, not a modal with a red button: the archive is checked, what it holds is read
 * out, the two modes are explained in words — Merge never moves reading progress backwards, Replace
 * takes a Safety Snapshot first — and only then can it run. An archive OneShelf cannot accept says why.
 */
export function BackupPanel() {
  const { t, language } = useI18n();
  const { data, error, reload } = useResource<BackupsResponse>("/api/backups");
  const [restoring, setRestoring] = useState<Backup | null>(null);
  const [preflight, setPreflight] = useState<{ generation: number; path: string; result: Preflight } | null>(null);
  const preflightGeneration = useRef(0);
  const restoreLocked = useRef(false);
  const [restoreBusy, setRestoreBusy] = useState(false);
  const [mode, setMode] = useState<"merge" | "replace">("merge");
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const backups = data?.backups ?? [];
  const currentPreflight = preflight?.generation === preflightGeneration.current
    && preflight.path === restoring?.path ? preflight.result : null;

  const closeRestore = () => {
    if (restoreLocked.current) return;
    preflightGeneration.current += 1;
    setRestoring(null);
    setPreflight(null);
    setProblem(null);
  };

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
    const generation = ++preflightGeneration.current;
    setRestoring(backup);
    setPreflight(null);
    setProblem(null);
    setMode("merge");
    try {
      const result = await api.post<Preflight>("/api/restore/preflight", { path: backup.path });
      if (preflightGeneration.current === generation) setPreflight({ generation, path: backup.path, result });
    } catch (error) {
      if (preflightGeneration.current === generation)
        setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    }
  };

  const restore = async () => {
    if (restoring === null || !currentPreflight?.ok || restoreLocked.current) return;
    restoreLocked.current = true;
    setRestoreBusy(true);
    try {
      await api.post("/api/restore", { path: restoring.path, mode });
      setMessage(t("backup.restored"));
      preflightGeneration.current += 1;
      setRestoring(null);
      setPreflight(null);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      restoreLocked.current = false;
      setRestoreBusy(false);
      reload();
    }
  };

  return (
    <section className="paper">
      <h2 className="display">{t("backup.title")}</h2>

      {error !== null && <><p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button></>}

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
            <span className="cards__meta">{new Date(backup.created_at).toLocaleString(language)}</span>
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
        <ModalSurface className="confirm confirm--wide" title={t("backup.restoreTitle")}
                      onClose={closeRestore}>
          <h2 className="display">{t("backup.restoreTitle")}</h2>
          {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}

          {currentPreflight === null && problem === null && <p>{t("state.loading")}</p>}
          {restoreBusy && <p role="status">{t("state.loading")}</p>}

          {currentPreflight !== null && (
            <>
              <section className="restore__step">
                <h3>{t("backup.holds")}</h3>
                <ul className="restore__counts">
                  {Object.entries(currentPreflight.counts).map(([what, count]) => (
                    <li key={what}>{count} {COUNT_KEYS.has(what) ? t(`backup.count.${what}` as StringKey) : what.replaceAll("_", " ")}</li>
                  ))}
                </ul>
              </section>

              {currentPreflight.plugins.length > 0 && (
                <section className="restore__step">
                  <h3>{t("backup.sources")}</h3>
                  <ul className="restore__plugins">
                    {currentPreflight.plugins.map((plugin) => (
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

              {currentPreflight.ok ? (
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
                  {currentPreflight.issues.map((issue) => <li key={issue} className="cards__warn">{issue}</li>)}
                </ul>
              )}
            </>
          )}

          <div className="confirm__actions">
            <button type="button" className="button" disabled={restoreBusy} onClick={closeRestore}>{t("common.cancel")}</button>
            {currentPreflight?.ok && (
              <button type="button" className="button button--primary" disabled={restoreBusy} onClick={() => void restore()}>
                {t("backup.restore")}
              </button>
            )}
          </div>
        </ModalSurface>
      )}
    </section>
  );
}
