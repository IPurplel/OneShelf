import { useCallback, useEffect, useState } from "react";

import { api } from "@/api/client";
import { useI18n } from "@/i18n/i18n";
import { ModalSurface } from "./ModalSurface";
import { LoadingState } from "./LoadingState";
import { Icon } from "./Icon";

type BrowseEntry = { name: string; path: string };
type BrowseResponse = { parent: string | null; current?: string; entries: BrowseEntry[] };

export function FolderPicker({ onSelect, onClose }: {
  onSelect: (path: string) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [current, setCurrent] = useState("");
  const [parent, setParent] = useState<string | null>(null);
  const [entries, setEntries] = useState<BrowseEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const browse = useCallback(async (path: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<BrowseResponse>("/api/storage/browse", { path });
      setCurrent(data.current ?? path);
      setParent(data.parent ?? null);
      setEntries(data.entries);
    } catch {
      setError("Could not read directory");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void browse(""); }, [browse]);

  return (
    <ModalSurface className="confirm folderpicker" title={t("storage.browse.title")} onClose={onClose}>
      <h2 className="display">{t("storage.browse.title")}</h2>

      {current && (
        <p className="folderpicker__current literal-path" dir="ltr">{current}</p>
      )}

      <div className="folderpicker__toolbar">
        {parent !== null && (
          <button type="button" className="chip" onClick={() => void browse(parent)}>
            <Icon name="close" size={14} /> {t("storage.browse.up")}
          </button>
        )}
      </div>

      {loading && <LoadingState />}
      {error && <p className="notice notice--problem">{error}</p>}

      {!loading && entries.length === 0 && (
        <p className="shelf__empty">{t("storage.browse.empty")}</p>
      )}

      {!loading && (
        <ul className="folderpicker__list">
          {entries.map((entry) => (
            <li key={entry.path}>
              <button type="button" className="folderpicker__entry"
                      onClick={() => void browse(entry.path)}>
                <span className="folderpicker__icon" aria-hidden="true">📁</span>
                <span dir="auto">{entry.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="confirm__actions">
        <button type="button" className="button" onClick={onClose}>{t("common.cancel")}</button>
        <button type="button" className="button button--primary" disabled={!current}
                onClick={() => { onSelect(current); onClose(); }}>
          {t("storage.browse.select")}
        </button>
      </div>
    </ModalSurface>
  );
}
