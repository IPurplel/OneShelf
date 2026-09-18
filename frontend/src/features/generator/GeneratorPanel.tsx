import { useState } from "react";

import { ApiError, api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { explain } from "@/features/sources/permissions";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";

type FieldSpec = { css?: string; json?: string; transforms?: unknown[]; required?: boolean; template?: string };
type Recipe = {
  request?: { url_template?: string };
  extract?: { items?: { css?: string }; fields?: Record<string, FieldSpec> };
};

type Draft = {
  id: string;
  state: string;
  start_url: string;
  package_path: string | null;
  manifest: { id: string; name: string; version: string; capabilities: string[] };
  recipes: Record<string, Recipe>;
  confidence: Record<string, string>;
  unsupported: Record<string, string>;
  notes: string[];
  fetches: string[];
  permissions: string[];
  rejected_domains: string[];
};

type TestReport = { passed: boolean; cases: number; failures: string[] };
type Diagnosis = { checked: string[]; broken: string[]; details: Record<string, string>; healthy: boolean };
type Change = { capability: string; field_name: string; before: string; after: string };
type Repair = { version: string; path: string; validated: boolean; changes: Change[]; notes: string[] };
type Source = { id: string; name: string; state: string };

const STATES: Record<string, StringKey> = {
  confirmed: "gen.state.confirmed", probable: "gen.state.probable",
  unknown: "gen.state.unknown", unsupported: "gen.state.unsupported",
};

function transformList(transforms: unknown[] | undefined): string {
  if (transforms === undefined) return "";
  return transforms.map((step) => (typeof step === "string" ? step : JSON.stringify(step))).join(" → ");
}

/**
 * The Adapter Generator (Master §12, §32.14).
 *
 * The generator looks at a page the developer can already read and proposes a declarative package. It
 * never installs anything by itself: each capability carries the state discovery actually reached, what
 * it could not work out is named with its reason, every selector can be read in the Recipe Inspector,
 * and the packaged tests must pass before installing is even offered. A submission bundle is written to
 * disk and goes nowhere.
 *
 * Repair follows the same rule: the selector diff is shown before a validated repair may be activated.
 */
export function GeneratorPanel() {
  const { t } = useI18n();
  const { data: sources } = useResource<{ sources: Source[] }>("/api/sources");
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [built, setBuilt] = useState<string | null>(null);
  const [report, setReport] = useState<TestReport | null>(null);
  const [installed, setInstalled] = useState<string | null>(null);
  const [bundle, setBundle] = useState<string | null>(null);
  const [diagnosis, setDiagnosis] = useState<{ id: string; report: Diagnosis } | null>(null);
  const [repair, setRepair] = useState<{ id: string; outcome: Repair } | null>(null);
  const [activated, setActivated] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const attempt = async <T,>(call: Promise<T>, then: (result: T) => void) => {
    setProblem(null);
    setBusy(true);
    try {
      then(await call);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      setBusy(false);
    }
  };

  const start = () => attempt(
    api.post<Draft>("/api/generator/drafts", { url: url.trim(), name: name.trim() }),
    (result) => { setDraft(result); setBuilt(null); setReport(null); setInstalled(null); setBundle(null); });

  return (
    <section className="paper">
      <h2 className="display">{t("settings.developer.generator")}</h2>
      <p className="firstrun__lede">{t("gen.help")}</p>

      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}

      <label className="field__label">
        {t("gen.url")}
        <input type="text" className="field" value={url} placeholder="https://example.org/browse"
               onChange={(event) => setUrl(event.target.value)} />
      </label>
      <label className="field__label">
        {t("gen.name")}
        <input type="text" className="field" value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <div className="firstrun__actions">
        <button type="button" className="button button--primary" disabled={busy} onClick={() => void start()}>
          {t("gen.start")}
        </button>
      </div>

      {draft !== null && (
        <div className="gen__draft">
          <dl className="details">
            <dt>{t("gen.pluginId")}</dt><dd>{draft.manifest.id}</dd>
            <dt>{t("gen.startUrl")}</dt><dd>{draft.start_url}</dd>
            <dt>{t("install.version")}</dt><dd>{draft.manifest.version}</dd>
          </dl>

          <h3 className="display">{t("gen.capabilities")}</h3>
          <ul className="gen__states">
            {Object.entries(draft.confidence).map(([capability, state]) => (
              <li key={capability}>
                <span className="cards__name">{capability}</span>
                <span className={`chip chip--${state}`}>{t(STATES[state] ?? "gen.state.unknown")}</span>
              </li>
            ))}
          </ul>

          {Object.keys(draft.unsupported).length > 0 && (
            <>
              <h3 className="display">{t("gen.unsupported")}</h3>
              <ul className="restore__issues">
                {Object.entries(draft.unsupported).map(([capability, reason]) => (
                  <li key={capability}><strong>{capability}</strong> — {reason}</li>
                ))}
              </ul>
            </>
          )}

          <h3 className="display">{t("install.permissions")}</h3>
          <ul className="install__permissions">
            {draft.permissions.map((permission) => (
              <li key={permission}>
                <span>{explain(permission, t)}</span>
                <code className="cards__meta">{permission}</code>
              </li>
            ))}
          </ul>
          {draft.rejected_domains.length > 0 && (
            <p className="cards__meta">
              {t("gen.rejected", { domains: draft.rejected_domains.join(", ") })}
            </p>
          )}

          {draft.notes.length > 0 && (
            <ul className="restore__counts">
              {draft.notes.map((note) => <li key={note} className="cards__meta">{note}</li>)}
            </ul>
          )}

          <div className="firstrun__actions">
            <button type="button" className="button" onClick={() => setInspecting((open) => !open)}>
              {t("gen.inspect")}
            </button>
            <button type="button" className="button" disabled={busy}
                    onClick={() => void attempt(
                      api.post<{ path: string }>(`/api/generator/drafts/${draft.id}/generate`),
                      (result) => { setBuilt(result.path); setReport(null); })}>
              {t("gen.build")}
            </button>
            {built !== null && (
              <button type="button" className="button" disabled={busy}
                      onClick={() => void attempt(
                        api.post<TestReport>(`/api/generator/drafts/${draft.id}/test`), setReport)}>
                {t("gen.runTests")}
              </button>
            )}
            <button type="button" className="button" disabled={busy}
                    onClick={() => void attempt(
                      api.post<{ path: string }>(`/api/generator/drafts/${draft.id}/submission`),
                      (result) => setBundle(result.path))}>
              {t("gen.bundle")}
            </button>
          </div>

          {built !== null && <p className="cards__meta">{t("gen.built", { path: built })}</p>}

          {report !== null && (report.passed ? (
            <p className="cards__ok">{t("install.testsPassed", { cases: report.cases })}</p>
          ) : (
            <>
              <p className="cards__warn">{t("install.testsFailed")}</p>
              <ul className="restore__issues">
                {report.failures.map((failure) => <li key={failure}>{failure}</li>)}
              </ul>
            </>
          ))}

          {report?.passed === true && installed === null && (
            <div className="firstrun__actions">
              <button type="button" className="button button--primary" disabled={busy}
                      onClick={() => void attempt(
                        api.post<{ plugin_id: string }>(`/api/generator/drafts/${draft.id}/install`,
                                                        { approved_permissions: draft.permissions }),
                        (result) => setInstalled(result.plugin_id))}>
                {t("install.action")}
              </button>
            </div>
          )}
          {installed !== null && <p className="notice" role="status">{t("install.done", { name: installed })}</p>}

          {bundle !== null && (
            <p className="notice" role="status">
              <code>{bundle}</code> <span>{t("gen.bundleKept")}</span>
            </p>
          )}

          {inspecting && (
            <section className="gen__inspector" aria-label={t("gen.inspector")}>
              {Object.entries(draft.recipes).map(([capability, recipe]) => (
                <div key={capability} className="gen__recipe">
                  <h4>{capability}</h4>
                  <dl className="details">
                    <dt>{t("gen.request")}</dt><dd><code>{recipe.request?.url_template ?? "—"}</code></dd>
                    <dt>{t("gen.items")}</dt><dd><code>{recipe.extract?.items?.css ?? "—"}</code></dd>
                  </dl>
                  <table className="gen__fields">
                    <thead>
                      <tr><th>{t("gen.field")}</th><th>{t("gen.selector")}</th><th>{t("gen.transforms")}</th></tr>
                    </thead>
                    <tbody>
                      {Object.entries(recipe.extract?.fields ?? {}).map(([field, spec]) => (
                        <tr key={field}>
                          <td>{field}</td>
                          <td><code>{spec.css ?? spec.json ?? spec.template ?? "—"}</code></td>
                          <td><code>{transformList(spec.transforms)}</code></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </section>
          )}
        </div>
      )}

      <h3 className="display">{t("gen.repair")}</h3>
      <p className="cards__meta">{t("gen.repairHelp")}</p>
      <ul className="cards">
        {(sources?.sources ?? []).map((source) => (
          <li key={source.id} className="cards__row">
            <span className="cards__name display">{source.name}</span>
            <button type="button" className="chip" disabled={busy}
                    onClick={() => void attempt(
                      api.post<Diagnosis>(`/api/generator/repair/${source.id}/diagnose`),
                      (result) => { setDiagnosis({ id: source.id, report: result });
                                    setRepair(null); setActivated(null); })}>
              {t("gen.check")}
            </button>
          </li>
        ))}
      </ul>

      {diagnosis !== null && (
        <div className="gen__diagnosis">
          {diagnosis.report.healthy ? (
            <p className="cards__ok">{t("gen.healthy")}</p>
          ) : (
            <>
              <ul className="restore__issues">
                {Object.entries(diagnosis.report.details).map(([capability, detail]) => (
                  <li key={capability}><strong>{capability}</strong> — {detail}</li>
                ))}
              </ul>
              <div className="firstrun__actions">
                <button type="button" className="button" disabled={busy}
                        onClick={() => void attempt(
                          api.post<Repair>(`/api/generator/repair/${diagnosis.id}`),
                          (result) => setRepair({ id: diagnosis.id, outcome: result }))}>
                  {t("gen.propose")}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {repair !== null && (
        <div className="gen__repair">
          <h4>{t("gen.changes")}</h4>
          <ul className="gen__changes">
            {repair.outcome.changes.map((change) => (
              <li key={`${change.capability}.${change.field_name}`}>
                <span className="cards__name">{change.capability} · {change.field_name}</span>
                <code className="gen__before">{change.before}</code>
                <code className="gen__after">{change.after}</code>
              </li>
            ))}
          </ul>
          {repair.outcome.notes.map((note) => <p key={note} className="cards__meta">{note}</p>)}
          {repair.outcome.validated ? (
            <div className="firstrun__actions">
              <button type="button" className="button button--primary" disabled={busy}
                      onClick={() => void attempt(
                        api.post<{ plugin_id: string }>(`/api/generator/repair/${repair.id}/activate`,
                                                        { approved_permissions: [], path: repair.outcome.path }),
                        (result) => setActivated(result.plugin_id))}>
                {t("gen.activate")}
              </button>
            </div>
          ) : (
            <p className="cards__warn">{t("gen.notValidated")}</p>
          )}
          {activated !== null && <p className="notice" role="status">{t("gen.activated", { name: activated })}</p>}
        </div>
      )}
    </section>
  );
}
