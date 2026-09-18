import { useState } from "react";

import { ApiError, api } from "@/api/client";
import { useI18n } from "@/i18n/i18n";
import { explain } from "./permissions";

type Review = {
  upload_id: string;
  id: string;
  name: string;
  version: string;
  description: string | null;
  publisher: string | null;
  sha256: string;
  capabilities: string[];
  browser_capabilities: string[];
  permissions: string[];
  auth_available: boolean;
  tests: { passed: boolean; cases: number; failures: string[] };
};

type Outcome = { plugin_id: string; version: string; state: string; added_permissions: string[] };

/**
 * Installing a source from a file (Master §10.2, §11, §32.12).
 *
 * The package is read and its own packaged tests are run before anything is offered: what the source
 * can do, who published it, what it may reach, and whether its tests passed. A package whose tests
 * failed cannot be installed from here at all, and permissions are granted only as shown — the install
 * request carries exactly the list on screen.
 */
export function InstallPanel({ onInstalled }: { onInstalled: () => void }) {
  const { t } = useI18n();
  const [review, setReview] = useState<Review | null>(null);
  const [installed, setInstalled] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const choose = async (file: File) => {
    setProblem(null);
    setInstalled(null);
    setReview(null);
    setBusy(true);
    try {
      const response = await fetch("/api/sources/uploads", {
        method: "POST", credentials: "same-origin", body: file,
        headers: { "Content-Type": "application/octet-stream" },
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new ApiError(response.status, payload?.error?.code ?? "INVALID_PACKAGE",
                           payload?.error?.message ?? t("state.offline"));
      }
      setReview(payload as Review);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      setBusy(false);
    }
  };

  const install = async () => {
    if (review === null) return;
    setProblem(null);
    setBusy(true);
    try {
      await api.post<Outcome>("/api/sources/install", {
        upload_id: review.upload_id, approved_permissions: review.permissions,
      });
      setInstalled(review.name);
      setReview(null);
      onInstalled();
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="paper">
      <h2 className="display">{t("install.title")}</h2>
      <p className="firstrun__lede">{t("install.help")}</p>

      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {installed !== null && (
        <p className="notice" role="status">{t("install.done", { name: installed })}</p>
      )}

      <label className="field__label">
        {t("install.choose")}
        <input type="file" accept=".osp" className="field" disabled={busy}
               onChange={(event) => {
                 const file = event.target.files?.[0];
                 if (file) void choose(file);
               }} />
      </label>

      {review !== null && (
        <div className="install__review">
          <dl className="details">
            <dt>{t("install.name")}</dt><dd>{review.name}</dd>
            <dt>{t("install.version")}</dt><dd>{review.version}</dd>
            <dt>{t("install.publisher")}</dt><dd>{review.publisher ?? t("install.noPublisher")}</dd>
            <dt>{t("sources.capabilities")}</dt><dd>{review.capabilities.join(", ")}</dd>
          </dl>
          {review.description !== null && <p>{review.description}</p>}

          <h3 className="display">{t("install.permissions")}</h3>
          <ul className="install__permissions">
            {review.permissions.map((permission) => (
              <li key={permission}>
                <span>{explain(permission, t)}</span>
                <code className="cards__meta">{permission}</code>
              </li>
            ))}
          </ul>
          <p className="cards__meta">{t("install.permissionsNote")}</p>

          <h3 className="display">{t("install.tests")}</h3>
          {review.tests.passed ? (
            <p className="cards__ok">{t("install.testsPassed", { cases: review.tests.cases })}</p>
          ) : (
            <>
              <p className="cards__warn">{t("install.testsFailed")}</p>
              <ul className="restore__issues">
                {review.tests.failures.map((failure) => <li key={failure}>{failure}</li>)}
              </ul>
            </>
          )}

          {review.tests.passed && (
            <div className="firstrun__actions">
              <button type="button" className="button button--primary" disabled={busy} onClick={() => void install()}>
                {t("install.action")}
              </button>
              <button type="button" className="button" onClick={() => setReview(null)}>{t("common.cancel")}</button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
