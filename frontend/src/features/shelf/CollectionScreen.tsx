import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Icon } from "@/components/Icon";
import { LoadingState } from "@/components/LoadingState";
import { WorkCard } from "@/components/WorkCard";
import { useI18n } from "@/i18n/i18n";
import type { ShelfWork } from "./shelves";

/** One of your own shelves: everything on it, its name to change, and works to take off (never out of the library). */
export function CollectionScreen() {
  const { collectionId = "" } = useParams();
  const { t, tn, errorText, direction } = useI18n();
  const navigate = useNavigate();
  const { data, error, reload } = useResource<{ id: string; name: string; works: ShelfWork[] }>(
    `/api/collections/${collectionId}`);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const act = async (call: Promise<unknown>, after?: () => void) => {
    setProblem(null);
    try {
      await call;
      after?.();
    } catch (failure) {
      setProblem(errorText(failure));
    } finally {
      reload();
    }
  };
  const rename = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    void act(api.patch(`/api/collections/${collectionId}`, { name: name.trim() }), () => setRenaming(false));
  };

  if (error !== null) {
    return <section className="screen"><p className="notice notice--problem" role="alert">{error}</p></section>;
  }
  if (data === null) return <section className="screen"><LoadingState /></section>;
  return (
    <section className="screen collection">
      <Link className="collection__back" to="/shelf">
        <span aria-hidden="true">{direction === "rtl" ? "→" : "←"}</span> {t("shelves.back")}
      </Link>
      {renaming ? (
        <form className="myshelves__new" onSubmit={rename}>
          <input className="field" aria-label={t("shelves.name")} value={name} maxLength={120}
                 onChange={(event) => setName(event.target.value)} autoFocus />
          <button type="submit" className="button button--primary">{t("shelves.save")}</button>
          <button type="button" className="button" onClick={() => setRenaming(false)}>{t("common.cancel")}</button>
        </form>
      ) : (
        <div className="collection__head">
          <h1 className="screen__title" dir="auto">{data.name}</h1>
          <button type="button" className="chip" onClick={() => { setName(data.name); setRenaming(true); }}>
            {t("shelves.rename")}
          </button>
          <button type="button" className="chip chip--danger" onClick={() => setDeleting(true)}>{t("shelves.delete")}</button>
        </div>
      )}
      <p className="screen__subtitle">{tn("shelves.count", data.works.length)}</p>
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {data.works.length === 0
        ? <p className="cards__meta">{t("shelves.emptyShelf")}</p>
        : <ul className="collection__works">
            {data.works.map((work) => (
              <li key={work.work_id} className="collection__item">
                <WorkCard work={{ work_id: work.work_id, title: work.title, cover_url: work.cover_url,
                                  content_type: work.content_type }} />
                <button type="button" className="resultcard__download collection__remove"
                        aria-label={t("shelves.remove", { title: work.title })}
                        title={t("shelves.remove", { title: work.title })}
                        onClick={() => void act(api.delete(`/api/collections/${collectionId}/works/${work.work_id}`))}>
                  <Icon name="close" size={18} />
                </button>
              </li>
            ))}
          </ul>}
      {deleting && (
        <ConfirmDialog title={t("shelves.deleteTitle", { name: data.name })} body={t("shelves.deleteBody")}
                       confirmLabel={t("shelves.delete")} danger onCancel={() => setDeleting(false)}
                       onConfirm={() => void act(api.delete(`/api/collections/${collectionId}`),
                                                 () => navigate("/shelf"))} />
      )}
    </section>
  );
}
