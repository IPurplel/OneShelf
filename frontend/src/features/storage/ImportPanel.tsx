import { useState } from "react";

import { ApiError, api } from "@/api/client";
import { useI18n } from "@/i18n/i18n";

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
  const { t } = useI18n();
  const [review, setReview] = useState<Review | null>(null);
  const [title, setTitle] = useState("");
  const [target, setTarget] = useState<string>("new");
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const choose = async (file: File) => {
    setProblem(null);
    setDone(false);
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
      const reviewed = payload as Review;
      setReview(reviewed);
      setTitle(reviewed.suggested_title);
      const confident = reviewed.suggestions.find((candidate) => candidate.confident);
      setTarget(confident ? confident.work_id : "new");
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    }
  };

  const importFile = async () => {
    if (review === null) return;
    setProblem(null);
    try {
      await api.post("/api/import", {
        upload_id: review.upload_id,
        mode: "copy",                                   // §37: Copy is the default; Move is explicit
        work_id: target === "new" ? undefined : target,
        title: target === "new" ? title : undefined,
        language: review.language ?? undefined,
      });
      setReview(null);
      setDone(true);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    }
  };

  return (
    <section className="paper">
      <h2 className="display">{t("import.title")}</h2>
      <p className="firstrun__lede">{t("import.help")}</p>

      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {done && <p className="notice" role="status">{t("import.done")}</p>}

      <label className="field__label">
        {t("import.choose")}
        <input type="file" accept=".cbz,.pdf,.epub" className="field"
               onChange={(event) => {
                 const file = event.target.files?.[0];
                 if (file) void choose(file);
               }} />
      </label>

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
            <label className="field__label">
              {t("import.titleField")}
              <input type="text" className="field" value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
          )}

          <div className="firstrun__actions">
            <button type="button" className="button button--primary" onClick={() => void importFile()}>
              {t("import.action")}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
