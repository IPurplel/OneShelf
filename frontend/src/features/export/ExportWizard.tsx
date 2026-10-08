import { useMemo, useRef, useState } from "react";

import { api } from "@/api/client";
import { apiErrorText } from "@/i18n/apiErrors";
import { useResource } from "@/api/useApi";
import { ModalSurface } from "@/components/ModalSurface";
import type { WorkDetails } from "@/api/types";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";
import { bytes } from "@/lib/format";

type Step = "content" | "format" | "destination" | "review";
type MissingPolicy = "export_downloaded_only" | "download_missing_then_export";

type Preview = {
  files: number;
  total_bytes: number;
  missing_units: string[];
  choices: string[];
  disclosure: { message: string; units: string[]; choices: string[] } | null;
};

type Report = { job_id: string; state: string; copied: number; skipped: number; failed: number; errors: string[] };

/**
 * The Export wizard (Master §34, §32.16): Content → Format → Destination → Review.
 *
 * Export copies; it never changes the library. When some of the selection is not downloaded, the wizard
 * says in the Master's own words that continuing would permanently download those items first, and the
 * request carries that acknowledgement explicitly (INV-21). Formats are chosen from what exists — nothing
 * is converted.
 */
export function ExportWizard({ workId, trackId, onClose }: { workId: string; trackId?: string | null; onClose: () => void }) {
  const { t, language } = useI18n();
  const { data, error, reload } = useResource<WorkDetails>(`/api/works/${workId}`,
    trackId ? { track_id: trackId } : undefined);
  const [step, setStep] = useState<Step>("content");
  const [selected, setSelected] = useState<Set<string> | null>(null);
  const [output, setOutput] = useState<"folder" | "zip">("folder");
  const [conflict, setConflict] = useState<"skip_identical" | "replace" | "keep_both">("skip_identical");
  const [destination, setDestination] = useState("");
  const [preview, setPreview] = useState<{ key: string; result: Preview } | null>(null);
  const previewGeneration = useRef(0);
  const latestSelection = useRef("");
  const [checking, setChecking] = useState(false);
  const [policy, setPolicy] = useState<MissingPolicy>("export_downloaded_only");
  const [report, setReport] = useState<Report | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const units = useMemo(() => data?.units ?? [], [data]);
  const chosen = selected ?? new Set(units.map((unit) => unit.id));
  const track = data?.tracks.find((candidate) => candidate.id === data.selected_track_id) ?? null;

  const body = () => ({
    work_id: workId,
    language: track?.language ?? "und",
    source_id: track?.source_id ?? "local",
    unit_ids: [...chosen],
    destination,
    output,
    conflict,
  });
  const selectionKey = JSON.stringify(body());
  latestSelection.current = selectionKey;
  const currentPreview = preview?.key === selectionKey ? preview.result : null;

  const invalidatePreview = () => {
    previewGeneration.current += 1;
    setPreview(null);
    setChecking(false);
    setProblem(null);
  };

  const toggle = (id: string) => {
    invalidatePreview();
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const check = async () => {
    if (checking) return;
    const request = body();
    const key = JSON.stringify(request);
    const generation = ++previewGeneration.current;
    setProblem(null);
    setPreview(null);
    setChecking(true);
    try {
      const result = await api.post<Preview>("/api/export/preview", request);
      if (previewGeneration.current === generation && latestSelection.current === key) {
        setPreview({ key, result });
        setStep("review");
      }
    } catch (error) {
      if (previewGeneration.current === generation && latestSelection.current === key)
        setProblem(apiErrorText(error, language, t));
    } finally {
      if (previewGeneration.current === generation) setChecking(false);
    }
  };

  const run = async () => {
    if (currentPreview === null) return;
    setProblem(null);
    try {
      setReport(await api.post<Report>("/api/export", {
        ...body(),
        missing_policy: policy,
        acknowledge_permanent_download: policy === "download_missing_then_export",
      }));
    } catch (error) {
      setProblem(apiErrorText(error, language, t));
    }
  };

  return (
    <ModalSurface className="confirm confirm--wide" title={t("export.title")} onClose={onClose}>
      <h2 className="display">{t("export.title")}</h2>
      <ol className="wizard__steps">
        {(["content", "format", "destination", "review"] as Step[]).map((candidate) => (
          <li key={candidate} aria-current={step === candidate ? "step" : undefined}>
            {t(`export.step.${candidate}` as StringKey)}
          </li>
        ))}
      </ol>

      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      {error !== null && <><p className="notice notice--problem" role="alert">{error === "offline" ? t("state.offline") : error}</p>
        <button type="button" className="button" onClick={reload}>{t("reader.retry")}</button></>}

      {step === "content" && (
        <fieldset className="panel__group" aria-label={t("export.content")}>
          <legend>{t("export.content")}</legend>
          {units.map((unit) => (
            <label key={unit.id} className="panel__choice">
              <input type="checkbox" checked={chosen.has(unit.id)} onChange={() => toggle(unit.id)} />
              <span>
                <span className="panel__choiceTitle" dir="auto">{unit.title ?? unit.id}</span>
                {!unit.downloaded && <span className="panel__choiceHelp">{t("export.notDownloaded")}</span>}
              </span>
            </label>
          ))}
        </fieldset>
      )}

      {step === "format" && (
        <>
          <fieldset className="panel__group" role="radiogroup" aria-label={t("export.format")}>
            <legend>{t("export.format")}</legend>
            {(["folder", "zip"] as const).map((candidate) => (
              <label key={candidate} className="panel__choice">
              <input type="radio" name="output" value={candidate} checked={output === candidate}
                       onChange={() => { invalidatePreview(); setOutput(candidate); }} />
                <span>
                  <span className="panel__choiceTitle">{t(`export.output.${candidate}` as StringKey)}</span>
                  <span className="panel__choiceHelp">{t(`export.output.${candidate}Help` as StringKey)}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <p className="cards__meta">{t("export.noConversion")}</p>
        </>
      )}

      {step === "destination" && (
        <>
          <label className="field__label">
            {t("export.destination")}
            <input type="text" className="field" dir="ltr" value={destination}
                   onChange={(event) => { invalidatePreview(); setDestination(event.target.value); }} />
          </label>
          <fieldset className="panel__group" role="radiogroup" aria-label={t("export.conflict")}>
            <legend>{t("export.conflict")}</legend>
            {(["skip_identical", "replace", "keep_both"] as const).map((candidate) => (
              <label key={candidate} className="panel__choice">
                <input type="radio" name="conflict" value={candidate} checked={conflict === candidate}
                       onChange={() => { invalidatePreview(); setConflict(candidate); }} />
                <span>{t(`export.conflict.${candidate}` as StringKey)}</span>
              </label>
            ))}
          </fieldset>
        </>
      )}

      {step === "review" && currentPreview !== null && report === null && (
        <>
          <dl className="details export__review">
            <dt>{t("export.format")}</dt><dd>{t(`export.output.${output}`)}</dd>
            <dt>{t("export.destination")}</dt><dd><bdi className="literal-path" dir="ltr">{destination}</bdi></dd>
            <dt>{t("export.conflict")}</dt><dd>{t(`export.conflict.${conflict}`)}</dd>
          </dl>
          <p>{t(currentPreview.files === 1 ? "export.summary.one" : "export.summary.other",
            { files: currentPreview.files, size: bytes(currentPreview.total_bytes) })}</p>
          {currentPreview.disclosure !== null && (
            <section className="restore__step">
              <p className="notice notice--problem">{currentPreview.disclosure.message}</p>
              <fieldset className="panel__group" role="radiogroup" aria-label={t("export.missing")}>
                <legend>{t("export.missing")}</legend>
                {(["export_downloaded_only", "download_missing_then_export"] as MissingPolicy[]).map((candidate) => (
                  <label key={candidate} className="panel__choice">
                    <input type="radio" name="policy" value={candidate} checked={policy === candidate}
                           onChange={() => setPolicy(candidate)} />
                    <span>{t(`export.policy.${candidate}` as StringKey)}</span>
                  </label>
                ))}
              </fieldset>
            </section>
          )}
        </>
      )}

      {report !== null && (
        <p role="status">
          {t(report.copied === 1 ? "export.done.one" : "export.done.other",
            { copied: report.copied, skipped: report.skipped, failed: report.failed })}
        </p>
      )}

      <div className="confirm__actions">
        <button type="button" className="button" onClick={onClose}>
          {report === null ? t("common.cancel") : t("export.close")}
        </button>
        {step !== "content" && report === null && (
          <button type="button" className="button" onClick={() => {
            setProblem(null);
            if (step === "review") setPreview(null);
            setStep(step === "review" ? "destination" : step === "destination" ? "format" : "content");
          }}>
            {t("export.back")}
          </button>
        )}
        {step === "content" && (
          <button type="button" className="button button--primary" disabled={data === null}
                  onClick={() => setStep("format")}>
            {t("export.next")}
          </button>
        )}
        {step === "format" && (
          <button type="button" className="button button--primary" onClick={() => setStep("destination")}>
            {t("export.next")}
          </button>
        )}
        {step === "destination" && (
          <button type="button" className="button button--primary" disabled={checking} onClick={() => void check()}>
            {t("export.next")}
          </button>
        )}
        {step === "review" && report === null && (
          <button type="button" className="button button--primary" disabled={currentPreview === null}
                  onClick={() => void run()}>
            {t("export.run")}
          </button>
        )}
      </div>
    </ModalSurface>
  );
}
