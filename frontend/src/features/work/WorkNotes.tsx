import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/api/client";
import { useResource } from "@/api/useApi";
import { useI18n } from "@/i18n/i18n";

type NotesData = { work_id: string; rating: number | null; note: string | null };

export function WorkNotes({ workId }: { workId: string }) {
  const { t } = useI18n();
  const { data, reload } = useResource<NotesData>(`/api/works/${workId}/notes`);
  const [note, setNote] = useState("");
  const [rating, setRating] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const loaded = useRef(false);

  useEffect(() => {
    if (!data || loaded.current) return;
    loaded.current = true;
    setNote(data.note ?? "");
    setRating(data.rating);
  }, [data]);

  useEffect(() => {
    loaded.current = false;
  }, [workId]);

  const save = useCallback(async () => {
    setSaving(true);
    setProblem(null);
    try {
      await api.put(`/api/works/${workId}/notes`, {
        rating,
        note: note.trim() || null,
      });
      reload();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Error");
    } finally {
      setSaving(false);
    }
  }, [workId, rating, note, reload]);

  const clear = useCallback(async () => {
    setSaving(true);
    setProblem(null);
    try {
      await api.delete(`/api/works/${workId}/notes`);
      setNote("");
      setRating(null);
      loaded.current = false;
      reload();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Error");
    } finally {
      setSaving(false);
    }
  }, [workId, reload]);

  const dirty = data !== null && (note.trim() !== (data.note ?? "") || rating !== data.rating);

  return (
    <section className="notes__section" aria-label={t("notes.title")}>
      <h3 className="display">{t("notes.title")}</h3>

      <div className="rating__stars" role="radiogroup" aria-label={t("rating.title")}>
        {Array.from({ length: 10 }, (_, i) => i + 1).map((star) => (
          <button key={star} type="button" className="rating__star"
                  aria-pressed={rating !== null && star <= rating}
                  aria-label={`${star}/10`}
                  onClick={() => setRating(rating === star ? null : star)}>
            ★
          </button>
        ))}
      </div>

      <textarea className="notes__textarea field" rows={4}
                placeholder={t("notes.placeholder")} value={note}
                onChange={(e) => setNote(e.target.value)} />

      {problem && <p className="notice notice--problem">{problem}</p>}

      <div className="notes__actions">
        <button type="button" className="button button--primary" disabled={saving || !dirty}
                onClick={() => void save()}>
          {t("notes.save")}
        </button>
        <button type="button" className="chip" disabled={saving || (data?.rating === null && !data?.note)}
                onClick={() => void clear()}>
          {t("notes.clear")}
        </button>
      </div>
    </section>
  );
}
