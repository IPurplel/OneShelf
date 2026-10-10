import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "@/api/client";
import { useI18n } from "@/i18n/i18n";
import { FilePicker } from "@/components/FilePicker";
import { apiErrorText } from "@/i18n/apiErrors";

type Suggestion = { work_id: string; title: string; tier: string; content_type: string | null; confident: boolean };

type Review = {
  upload_id: string;
  format: string;
  suggested_title: string;
  language: string | null;
  page_count: number | null;
  warnings: string[];
  suggestions: Suggestion[];
};

/**
 * Import (Master §37, §32.14).
 *
 * The file is reviewed before anything is written: format, pages, and any work it might belong to. An
 * association is always offered as a choice — never decided for you — and Copy is the default, so the
 * file you picked stays where it is.
 */
export function ImportPanel() {
  const { t, language } = useI18n();
  const [review, setReview] = useState<Review | null>(null);
  const [title, setTitle] = useState("");
  const [target, setTarget] = useState<string>("new");
  const [problem, setProblem] = useState<string | null>(null);
  const [doneWorkId, setDoneWorkId] = useState<string | null>(null);
  const [titleTouched, setTitleTouched] = useState(false);
  const [pickerKey, setPickerKey] = useState(0);

  const [reviewing, setReviewing] = useState(false);
  const [importing, setImporting] = useState(false);
  const generation = useRef(0);
  const submitting = useRef(false);
  const titleInput = useRef<HTMLInputElement>(null);
  const titleError = target === "new" && titleTouched && title.trim().length === 0;
  useEffect(() => () => { generation.current++; }, []);

  const choose = async (file: File) => {
    if (submitting.current) return;
    const current = ++generation.current;
    setReview(null);
    setReviewing(true);
    setProblem(null);
    setDoneWorkId(null);
    setTitleTouched(false);
    try {
      const response = await fetch(`/api/import/uploads?filename=${encodeURIComponent(file.name)}`, {
        method: "POST", credentials: "same-origin", body: file,
        headers: { "Content-Type": "application/octet-stream" },
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new ApiError(response.status, payload?.error?.code ?? "IMPORT_REJECTED",
                           payload?.error?.message ?? t("state.offline"));
      }
      if (current !== generation.current) return;
      const reviewed = payload as Review;
      setReview(reviewed);
      setTitle(reviewed.suggested_title);
      const confident = reviewed.suggestions.find((candidate) => candidate.confident);
      setTarget(confident ? confident.work_id : "new");
    } catch (error) {
      if (current === generation.current) setProblem(apiErrorText(error, language, t));
    } finally {
      if (current === generation.current) setReviewing(false);
    }
  };

  const importFile = async () => {
    if (review === null || submitting.current) return;
    if (target === "new" && !title.trim()) {
      setTitleTouched(true);
      titleInput.current?.focus();
      requestAnimationFrame(() => titleInput.current?.scrollIntoView?.({ block: "center" }));
      return;
    }
    submitting.current = true;
    setImporting(true);
    setProblem(null);
    try {
      const outcome = await api.post<{ work_id: string }>("/api/import", {
        upload_id: review.upload_id,
        mode: "copy",                                   // §37: Copy is the default; Move is explicit
        work_id: target === "new" ? undefined : target,
        title: target === "new" ? title.trim() : undefined,
        language: review.language ?? undefined,
      });
      setReview(null);
      setDoneWorkId(outcome.work_id);
      setPickerKey((current) => current + 1);
    } catch (error) {
      setProblem(apiErrorText(error, language, t));
    } finally {
      submitting.current = false;
      setImporting(false);
    }
  };

  return (
    <section className="paper">
      <h2 className="display">{t("import.title")}</h2>
      <p className="firstrun__lede">{t("import.help")}</p>

      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {reviewing && <p role="status">{t("state.loading")}</p>}
      {doneWorkId !== null && (
        <div className="notice import__success" role="status">
          <span>{t("import.done")}</span>
          <Link className="button" to={`/works/${encodeURIComponent(doneWorkId)}`}>{t("import.openWork")}</Link>
        </div>
      )}

      <FilePicker key={pickerKey} label={t("import.choose")} accept=".cbz,.pdf,.epub" disabled={importing}
                  onChoose={(file) => void choose(file)} />

      {review !== null && (
        <div className="import__review">
          <p className="cards__meta">
            <span>{review.format.toUpperCase()}</span>
            {review.page_count !== null && <span>{t("import.pages", { count: review.page_count })}</span>}
            {review.language && <span>{review.language}</span>}
          </p>

          {review.warnings.map((warning) => (
            <p key={warning} className="notice notice--problem">{warning}</p>
          ))}

          {review.suggestions.length > 0 && (
            <fieldset className="panel__group" role="radiogroup" aria-label={t("import.where")}>
              <legend>{t("import.where")}</legend>
              {review.suggestions.map((suggestion) => (
                <label key={suggestion.work_id} className="panel__choice">
                  <input type="radio" name="target" value={suggestion.work_id} checked={target === suggestion.work_id}
                         onChange={() => setTarget(suggestion.work_id)} />
                  <span>{suggestion.title}</span>
                </label>
              ))}
              <label className="panel__choice">
                <input type="radio" name="target" value="new" checked={target === "new"}
                       onChange={() => setTarget("new")} />
                <span>{t("import.newWork")}</span>
              </label>
            </fieldset>
          )}

          {target === "new" && (
            <div className="field__label">
              <label htmlFor="import-title">{t("import.titleField")}</label>
              <input id="import-title" ref={titleInput} type="text" className="field" value={title}
                     aria-invalid={titleError} aria-describedby={titleError ? "import-title-error" : undefined}
                     onChange={(event) => setTitle(event.target.value)} />
              {titleError && <span id="import-title-error" className="field__error" role="alert">
                {t("import.titleRequired")}
              </span>}
            </div>
          )}

          <div className="firstrun__actions">
            <button type="button" className="button button--primary" disabled={importing} aria-busy={importing} onClick={() => void importFile()}>
              {t("import.action")}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
