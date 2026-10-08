import { useRef, useState } from "react";

import { api } from "@/api/client";
import { apiErrorText } from "@/i18n/apiErrors";
import { useResource } from "@/api/useApi";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ModalSurface } from "@/components/ModalSurface";
import { LoadingState } from "@/components/LoadingState";
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
  const { t, language } = useI18n();
  const { data, error, loading, reload } = useResource<{ roots: Root[] }>("/api/storage");
  const [adding, setAdding] = useState(false);
  const [moving, setMoving] = useState<Root | null>(null);
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [destination, setDestination] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const addLocked = useRef(false);
  const [addBusy, setAddBusy] = useState(false);

  const addRoot = async () => {
    if (addLocked.current) return;
    addLocked.current = true;
    setAddBusy(true);
    setProblem(null);
    try {
      await api.post("/api/storage/roots", { name, path });
      setAdding(false);
    } catch (error) {
      setProblem(apiErrorText(error, language, t));
    } finally {
      addLocked.current = false;
      setAddBusy(false);
      reload();
    }
  };

  const run = async (call: Promise<unknown>, after?: () => void) => {
    setProblem(null);
    try {
      await call;
      after?.();
    } catch (error) {
      setProblem(apiErrorText(error, language, t));
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
      setProblem(apiErrorText(error, language, t));
    }
  };

  return (
    <section className="paper">
      {error !== null && <><p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button></>}
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {message !== null && <p className="notice" role="status">{message}</p>}
      {loading && <LoadingState />}
      {data !== null && !loading && data.roots.length === 0 && <p className="shelf__empty">{t("storage.empty")}</p>}

      <ul className="cards">
        {(data?.roots ?? []).map((root) => (
          <li key={root.id} className="cards__row">
            <span className="cards__name display">{root.name}</span>
            <bdi className="cards__meta literal-path" dir="ltr">{root.path}</bdi>
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
              <button type="button" className="chip" disabled={loading}
                      onClick={() => void run(api.post(`/api/storage/roots/${root.id}/default`))}>
                {t("storage.makeDefault")}
              </button>
            )}
            <button type="button" className="chip" disabled={loading} onClick={() => setMoving(root)}>{t("storage.move")}</button>
          </li>
        ))}
      </ul>

      <div className="firstrun__actions">
        <button type="button" className="button" disabled={loading || error !== null} onClick={() => setAdding(true)}>{t("storage.add")}</button>
        <button type="button" className="button" disabled={loading || error !== null} onClick={() => void scan()}>{t("storage.scan")}</button>
      </div>

      {adding && (
        <ModalSurface className="confirm" title={t("storage.addTitle")}
                      onClose={() => { if (!addLocked.current) setAdding(false); }}>
          {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
          <h2 className="display">{t("storage.addTitle")}</h2>
          <label className="field__label">
            {t("storage.folder")}
            <input type="text" className="field" dir="ltr" value={path} onChange={(event) => setPath(event.target.value)} />
          </label>
          <label className="field__label">
            {t("storage.name")}
            <input type="text" className="field" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <div className="confirm__actions">
            <button type="button" className="button" disabled={addBusy}
                    onClick={() => setAdding(false)}>{t("common.cancel")}</button>
            <button type="button" className="button button--primary" disabled={addBusy}
                    onClick={() => void addRoot()}>
              {t("storage.addAction")}
            </button>
          </div>
          {addBusy && <p role="status">{t("state.loading")}</p>}
        </ModalSurface>
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
            <input type="text" className="field" dir="ltr" value={destination}
                   onChange={(event) => setDestination(event.target.value)} />
          </label>
        </ConfirmDialog>
      )}
    </section>
  );
}
