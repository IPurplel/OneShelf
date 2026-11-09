import { type FormEvent, useState } from "react";

import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { Shelf } from "@/components/Shelf";
import { WorkCard } from "@/components/WorkCard";
import { useI18n } from "@/i18n/i18n";
import type { Collection } from "./shelves";

/**
 * Shelves you make yourself ("Novels", "Manga", "For the summer"), each drawn as a real shelf of its covers
 * at the top of My Shelf. Tags stay the quick filter below; these are the catalogue you arrange.
 */
export function MyShelves() {
  const { t, tn, errorText } = useI18n();
  const { data, reload } = useResource<{ collections: Collection[] }>("/api/collections");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setProblem(null);
    try {
      await api.post("/api/collections", { name: name.trim() });
      setName("");
      setCreating(false);
      reload();
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  // A library that cannot list its shelves right now still shows everything else on My Shelf.
  if (data === null) return null;
  const shelves = data.collections ?? [];
  return (
    <section className="myshelves" aria-labelledby="myshelves-title">
      <header className="myshelves__head">
        <h2 className="display" id="myshelves-title">{t("shelves.title")}</h2>
        {creating ? (
          <form className="myshelves__new" onSubmit={(event) => void create(event)}>
            <input className="field" aria-label={t("shelves.name")} placeholder={t("shelves.namePlaceholder")}
                   value={name} maxLength={120} onChange={(event) => setName(event.target.value)} autoFocus />
            <button type="submit" className="button button--primary">{t("shelves.create")}</button>
            <button type="button" className="button" onClick={() => { setCreating(false); setName(""); }}>
              {t("common.cancel")}
            </button>
          </form>
        ) : (
          <button type="button" className="chip chip--accent" onClick={() => setCreating(true)}>{t("shelves.new")}</button>
        )}
      </header>
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {shelves.length === 0 && <p className="cards__meta myshelves__empty">{t("shelves.empty")}</p>}
      {shelves.map((collection) => (
        <Shelf key={collection.id} title={collection.name} id={`myshelf-${collection.id}`}
               viewAllHref={`/shelves/${collection.id}`} compactRow>
          {collection.works.length === 0
            ? <p className="shelf__empty">{t("shelves.emptyShelf")}</p>
            : collection.works.map((work) => (
                <WorkCard key={work.work_id} size="compact"
                          work={{ work_id: work.work_id, title: work.title, cover_url: work.cover_url,
                                  content_type: work.content_type }} />
              ))}
          {collection.work_count > collection.works.length && (
            <p className="cards__meta">{tn("shelves.more", collection.work_count - collection.works.length)}</p>
          )}
        </Shelf>
      ))}
    </section>
  );
}
