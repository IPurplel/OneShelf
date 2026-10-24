import { useCallback, useState } from "react";

import { api, ApiError } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";
import { Drawer } from "@/components/Drawer";

type Tag = { id: string; name: string; color: string | null; work_count: number };

export function TagsDrawer({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const { data, reload } = useResource<{ tags: Tag[] }>("/api/tags");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const create = useCallback(async () => {
    if (!name.trim()) return;
    setProblem(null);
    try {
      await api.post("/api/tags", { name: name.trim() });
      setName("");
      setCreating(false);
      reload();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Error");
    }
  }, [name, reload]);

  const remove = useCallback(async (tagId: string) => {
    await api.delete(`/api/tags/${tagId}`);
    reload();
  }, [reload]);

  return (
    <Drawer title={t("tags.title")} onClose={onClose}>
      {problem && <p className="notice notice--problem">{problem}</p>}
      <ul className="drawer__units">
        {(data?.tags ?? []).map((tag) => (
          <li key={tag.id} className="drawer__unit">
            <span className="drawer__unitTitle">
              {tag.color && <span className="tags__dot" style={{ background: tag.color }} />}
              {tag.name}
            </span>
            <span className="drawer__unitState">{tag.work_count}</span>
            <button type="button" className="chip" onClick={() => void remove(tag.id)}>{t("tags.remove")}</button>
          </li>
        ))}
        {data?.tags.length === 0 && <li className="shelf__empty">{t("tags.empty")}</li>}
      </ul>

      {creating ? (
        <div className="tags__create">
          <input type="text" className="field" value={name} aria-label={t("tags.name")}
                 placeholder={t("tags.name")} onChange={(e) => setName(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") void create(); }} autoFocus />
          <button type="button" className="button button--primary" onClick={() => void create()}>{t("tags.add")}</button>
          <button type="button" className="chip" onClick={() => setCreating(false)}>{t("common.cancel")}</button>
        </div>
      ) : (
        <button type="button" className="button" onClick={() => setCreating(true)}>{t("tags.create")}</button>
      )}
    </Drawer>
  );
}
