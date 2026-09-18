import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import type { Unit, WorkDetails } from "@/api/types";
import { useI18n } from "@/i18n/i18n";
import { ContentsDrawer } from "./ContentsDrawer";
import { SettingsPanel } from "./SettingsPanel";
import { DEFAULT_SETTINGS, loadSettings, saveSettings } from "./settings";
import type { ReaderSettings } from "./settings";
import { useProgress } from "./useProgress";

type Page = { index: number; label: string | null; url: string | null };
type PagesResponse = { reading_unit_id: string; pages: Page[] };

const IDLE_MS = 3000;

/**
 * The Sequential Reader (Master §26).
 *
 * Content first: three layers only — content, reading controls, and advanced actions behind More. The
 * controls auto-hide when idle but never while a panel is open, progress is written with the revision
 * this tab last saw, and the end of a unit offers the *next unit in Source Track order*, never
 * "chapter + 1" (INV-24).
 */
export function ReaderScreen({ unitId, workId }: { unitId?: string; workId?: string }) {
  const params = useParams();
  const [search] = useSearchParams();
  const id = unitId ?? params.unitId ?? "";
  const work = workId ?? search.get("work") ?? "";
  const { t } = useI18n();

  const { data: pageData, error: pageError } = useResource<PagesResponse>(`/api/reader/units/${id}/pages`);
  const { data: details } = useResource<WorkDetails>(`/api/works/${work}`);
  const pages = useMemo(() => pageData?.pages ?? [], [pageData]);

  const [settings, setSettings] = useState<ReaderSettings>(DEFAULT_SETTINGS);
  const [panel, setPanel] = useState<null | "contents" | "settings">(null);
  const [controlsVisible, setControlsVisible] = useState(true);
  const [index, setIndex] = useState(0);
  const [atEnd, setAtEnd] = useState(false);
  const [failed, setFailed] = useState<Set<number>>(new Set());
  const indexRef = useRef(0);
  const { record, flush } = useProgress(id);

  const units = useMemo(() => details?.units ?? [], [details]);
  const unit = units.find((candidate) => candidate.id === id) ?? null;
  const next = nextInSourceOrder(units, id);

  useEffect(() => {
    setSettings(loadSettings(details?.work.id ?? null, details?.work.content_type ?? null));
  }, [details?.work.id, details?.work.content_type]);

  const changeSettings = useCallback((update: Partial<ReaderSettings>) => {
    setSettings((current) => {
      const merged = { ...current, ...update };
      saveSettings(details?.work.id ?? null, merged);
      return merged;
    });
  }, [details?.work.id]);

  // Controls auto-hide when idle, and never while a panel is open (§26.3).
  useEffect(() => {
    if (panel !== null) {
      setControlsVisible(true);
      return;
    }
    if (!controlsVisible) return;
    const timer = setTimeout(() => setControlsVisible(false), IDLE_MS);
    return () => clearTimeout(timer);
  }, [panel, controlsVisible, index]);

  const show = useCallback(() => setControlsVisible(true), []);

  const step = useCallback((delta: number) => {
    const target = indexRef.current + delta;
    if (pages.length > 0 && target >= pages.length) {
      setAtEnd(true);
      return;
    }
    const clamped = Math.max(0, target);
    indexRef.current = clamped;
    setIndex(clamped);
    setAtEnd(false);
    const fraction = pages.length === 0 ? 0 : (clamped + 1) / pages.length;
    record(fraction, { page: clamped + 1 });
  }, [pages.length, record]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setPanel(null); return; }
      if (panel !== null) return;
      const forward = settings.direction === "rtl" ? "ArrowLeft" : "ArrowRight";
      const back = settings.direction === "rtl" ? "ArrowRight" : "ArrowLeft";
      if (event.key === forward || event.key === "ArrowDown") { step(1); event.preventDefault(); }
      else if (event.key === back || event.key === "ArrowUp") { step(-1); event.preventDefault(); }
      else if (event.key === " ") { step(event.shiftKey ? -1 : 1); event.preventDefault(); }
      else if (event.key === "t") setPanel("contents");
      else if (event.key === "s") setPanel("settings");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panel, settings.direction, step]);

  const visible = visiblePages(pages, index, settings.mode);

  return (
    <div className={`reader reader--${settings.background}`} onMouseMove={show}>
      <div role="toolbar" aria-label={t("reader.controls")} className="reader__bar reader__bar--top"
           data-hidden={controlsVisible ? "false" : "true"}>
        <Link className="reader__button" to={work ? `/works/${work}` : "/shelf"} onClick={flush}>
          {t("reader.back")}
        </Link>
        <span className="reader__title">{details?.work.title ?? ""}</span>
        <span className="reader__unit">{unit?.title ?? ""}</span>
        <button type="button" className="reader__button" onClick={() => setPanel("contents")}>
          {t("reader.contents")}
        </button>
        <button type="button" className="reader__button" onClick={() => setPanel("settings")}>
          {t("reader.settings")}
        </button>
        <button type="button" className="reader__button"
                onClick={() => void api.post(`/api/reader/units/${id}/mark-read`, {})}>
          {t("reader.markRead")}
        </button>
      </div>

      <div className="reader__stage" data-testid="reader-stage" data-mode={settings.mode}
           data-direction={settings.direction} data-fit={settings.fit}>
        {pageError !== null && <p className="notice notice--problem" role="alert">{t("state.offline")}</p>}
        {visible.map((page) => (
          failed.has(page.index) ? (
            <div key={page.index} className="reader__failed" role="group" aria-label={t("reader.pageFailed")}>
              <p>{t("reader.pageFailed")}</p>
              <button type="button" onClick={() => setFailed((set) => {
                const copy = new Set(set);
                copy.delete(page.index);
                return copy;
              })}>{t("reader.retry")}</button>
            </div>
          ) : (
            <img key={page.index} className="reader__page" src={`/api/reader/units/${id}/pages/${page.index}`}
                 alt={t("reader.page", { index: page.label ?? page.index })} loading="lazy"
                 onError={() => setFailed((set) => new Set(set).add(page.index))} />
          )
        ))}
        {atEnd && <EndOfUnit unit={unit} next={next} workId={work} />}
      </div>

      <div role="toolbar" aria-label={t("reader.progressBar")} className="reader__bar reader__bar--bottom"
           data-hidden={controlsVisible ? "false" : "true"}>
        <span className="reader__progress">
          {pages.length > 0 ? `${Math.min(index + 1, pages.length)} / ${pages.length}` : ""}
        </span>
      </div>

      {panel === "contents" && <ContentsDrawer units={units} currentId={id} workId={work} onClose={() => setPanel(null)} />}
      {panel === "settings" && (
        <SettingsPanel settings={settings} onChange={changeSettings} onClose={() => setPanel(null)} />
      )}
    </div>
  );
}

function visiblePages(pages: Page[], index: number, mode: ReaderSettings["mode"]): Page[] {
  if (mode === "long_strip") return pages;
  if (mode === "double") return pages.slice(index, index + 2);
  return pages.slice(index, index + 1);
}

/** The next unit is the next one in Source Track order — a Special or an Extra, if that is what follows. */
function nextInSourceOrder(units: Unit[], currentId: string): Unit | null {
  const ordered = [...units].sort((a, b) => a.order - b.order);
  const position = ordered.findIndex((unit) => unit.id === currentId);
  return position >= 0 && position + 1 < ordered.length ? ordered[position + 1]! : null;
}

function EndOfUnit({ unit, next, workId }: { unit: Unit | null; next: Unit | null; workId: string }) {
  const { t } = useI18n();
  return (
    <section className="reader__end" role="region" aria-label={t("reader.end", { unit: unit?.title ?? "" })}>
      <h2 className="display">{t("reader.end", { unit: unit?.title ?? "" })}</h2>
      {next && (
        <Link className="button button--primary" to={`/read/${next.id}${workId ? `?work=${workId}` : ""}`}>
          {t("reader.next", { unit: next.title ?? next.id })}
        </Link>
      )}
      <Link className="button" to={workId ? `/works/${workId}` : "/shelf"}>{t("reader.backToWork")}</Link>
    </section>
  );
}
