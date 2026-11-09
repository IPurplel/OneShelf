import { type FormEvent, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "@/api/client";
import { Drawer } from "@/components/Drawer";
import { useI18n } from "@/i18n/i18n";
import type { Collection } from "./shelves";

/** Which of your shelves a work stands on: tick to put it there, untick to take it off, or make a new one. */
export function ShelvesPicker({ workId, title, onClose }: { workId: string; title: string; onClose: () => void }) {
  const { t, errorText } = useI18n();
  const [shelves, setShelves] = useState<Collection[] | null>(null);
  const [holding, setHolding] = useState<Set<string>>(new Set());
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const load = async () => {
    try {
      const [list, member] = await Promise.all([
        api.get<{ collections: Collection[] }>("/api/collections"),
        api.get<{ collection_ids: string[] }>(`/api/works/${workId}/collections`),
      ]);
      setShelves(list.collections);
      setHolding(new Set(member.collection_ids));
    } catch (error) {
      setProblem(errorText(error));
    }
  };
  useEffect(() => { void load(); }, [workId]);   // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = async (id: string, on: boolean) => {
    setProblem(null);
    setHolding((current) => {
      const next = new Set(current);
      if (on) next.add(id); else next.delete(id);
      return next;
    });
    try {
      await (on ? api.post(`/api/collections/${id}/works/${workId}`)
                : api.delete(`/api/collections/${id}/works/${workId}`));
    } catch (error) {
      setProblem(errorText(error));
      void load();
    }
  };

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setProblem(null);
    try {
      const made = await api.post<{ id: string }>("/api/collections", { name: name.trim() });
      await api.post(`/api/collections/${made.id}/works/${workId}`);
      setName("");
      await load();
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  return createPortal(
    <Drawer title={t("shelves.pickTitle", { title })} onClose={onClose}>
      <p className="cards__meta">{t("shelves.pickHelp")}</p>
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {shelves !== null && (
        <ul className="choice shelvespicker">
          {shelves.map((shelf) => (
            <li key={shelf.id}>
              <label className="shelvespicker__row">
                <input type="checkbox" checked={holding.has(shelf.id)}
                       onChange={(event) => void toggle(shelf.id, event.target.checked)} />
                <span dir="auto">{shelf.name}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <form className="myshelves__new" onSubmit={(event) => void create(event)}>
        <input className="field" aria-label={t("shelves.name")} placeholder={t("shelves.namePlaceholder")}
               value={name} maxLength={120} onChange={(event) => setName(event.target.value)} />
        <button type="submit" className="button">{t("shelves.createAndAdd")}</button>
      </form>
    </Drawer>, document.body);
}
