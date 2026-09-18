import { useState } from "react";

import { ApiError, api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useI18n } from "@/i18n/i18n";
import { bytes } from "@/lib/format";

type Root = {
  id: string; name: string; path: string; is_default: boolean; available: boolean; reason: string | null;
  total?: number; free?: number; reserve?: number; state?: string;
};

/**
 * Storage locations (Master §24, §32.14).
 *
 * An offline disk is "unavailable", never "missing files": nothing is cleaned up and nothing is claimed
 * lost. Moving a location explains that the old copy is kept and that an interrupted move resumes.
 */
export function StoragePanel() {
  const { t } = useI18n();
  const { data, reload } = useResource<{ roots: Root[] }>("/api/storage");
  const [adding, setAdding] = useState(false);
  const [moving, setMoving] = useState<Root | null>(null);
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [destination, setDestination] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const run = async (call: Promise<unknown>, after?: () => void) => {
    setProblem(null);
    try {
      await call;
      after?.();
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      reload();
    }
  };

  const scan = async () => {
    setProblem(null);
    try {
      const report = await api.post<{ checked: number; missing: number; recovered: number; corrupt: number }>(
        "/api/storage/scan");
      setMessage(t("storage.scanned", report));
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    }
  };

  return (
    <section className="paper">
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {message !== null && <p className="notice" role="status">{message}</p>}

      <ul className="cards">
        {(data?.roots ?? []).map((root) => (
          <li key={root.id} className="cards__row">
            <span className="cards__name display">{root.name}</span>
            <span className="cards__meta">{root.path}</span>
            {root.available ? (
              <>
                <span className="cards__meta">
                  {t("settings.free", { free: bytes(root.free ?? 0), total: bytes(root.total ?? 0) })}
                </span>
                <span className="cards__meta">{t("settings.reserve", { reserve: bytes(root.reserve ?? 0) })}</span>
              </>
            ) : (
              <>
                <span className="cards__warn">{t("storage.unavailable")}</span>
                <span className="cards__meta">{root.reason}</span>
              </>
            )}
            {root.is_default && <span className="cards__ok">{t("storage.default")}</span>}
            {!root.is_default && root.available && (
              <button type="button" className="chip"
                      onClick={() => void run(api.post(`/api/storage/roots/${root.id}/default`))}>
                {t("storage.makeDefault")}
              </button>
            )}
            <button type="button" className="chip" onClick={() => setMoving(root)}>{t("storage.move")}</button>
          </li>
        ))}
      </ul>

      <div className="firstrun__actions">
        <button type="button" className="button" onClick={() => setAdding(true)}>{t("storage.add")}</button>
        <button type="button" className="button" onClick={() => void scan()}>{t("storage.scan")}</button>
      </div>

      {adding && (
        <div className="confirm" role="dialog" aria-modal="true" aria-label={t("storage.addTitle")}>
          <h2 className="display">{t("storage.addTitle")}</h2>
          <label className="field__label">
            {t("storage.folder")}
            <input type="text" className="field" value={path} onChange={(event) => setPath(event.target.value)} />
          </label>
          <label className="field__label">
            {t("storage.name")}
            <input type="text" className="field" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <div className="confirm__actions">
            <button type="button" className="button" onClick={() => setAdding(false)}>{t("common.cancel")}</button>
            <button type="button" className="button button--primary"
                    onClick={() => void run(api.post("/api/storage/roots", { name, path }), () => setAdding(false))}>
              {t("storage.addAction")}
            </button>
          </div>
        </div>
      )}

      {moving !== null && (
        <ConfirmDialog
          title={t("storage.moveTitle")}
          body={t("storage.moveBody")}
          confirmLabel={t("storage.moveAction")}
          onCancel={() => setMoving(null)}
          onConfirm={() => void run(
            api.post(`/api/storage/roots/${moving.id}/migrate`, { path: destination }), () => setMoving(null))}
        >
          <label className="field__label">
            {t("storage.moveField")}
            <input type="text" className="field" value={destination}
                   onChange={(event) => setDestination(event.target.value)} />
          </label>
        </ConfirmDialog>
      )}
    </section>
  );
}
