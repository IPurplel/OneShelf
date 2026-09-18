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
const ZOOM_STEP = 1.25;
const ZOOM_MIN = 1;
const ZOOM_MAX = 4;
const SWIPE_MIN = 60;

const clampZoom = (value: number) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Number(value.toFixed(3))));

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
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [fullscreen, setFullscreen] = useState(false);
  const [more, setMore] = useState(false);
  const indexRef = useRef(0);
  const stage = useRef<HTMLDivElement | null>(null);
  const touch = useRef<{ x: number; y: number; spread: number | null } | null>(null);
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
    if (panel !== null || more) {
      setControlsVisible(true);
      return;
    }
    if (!controlsVisible) return;
    const timer = setTimeout(() => setControlsVisible(false), IDLE_MS);
    return () => clearTimeout(timer);
  }, [panel, more, controlsVisible, index]);

  const show = useCallback(() => setControlsVisible(true), []);

  const step = useCallback((delta: number) => {
    const stride = settings.mode === "double"
      ? Math.max(1, visiblePages(pages, indexRef.current, settings).length) : 1;
    const target = indexRef.current + delta * stride;
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
  }, [pages, settings, record]);

  const changeZoom = useCallback((factor: number) => {
    setZoom((current) => {
      const next = clampZoom(current * factor);
      if (next === ZOOM_MIN) setPan({ x: 0, y: 0 });     // back to the fit means back to the middle
      return next;
    });
  }, []);

  const resetZoom = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  /** Full screen is the reader's own (§26.5): the stage goes fullscreen, controls and all. */
  const toggleFullscreen = useCallback(() => {
    const element = stage.current;
    if (document.fullscreenElement !== null && document.fullscreenElement !== undefined) {
      void document.exitFullscreen?.();
      return;
    }
    void element?.requestFullscreen?.();
  }, []);

  useEffect(() => {
    const onChange = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setPanel(null); setMore(false); return; }
      if (panel !== null) return;
      const forward = settings.direction === "rtl" ? "ArrowLeft" : "ArrowRight";
      const back = settings.direction === "rtl" ? "ArrowRight" : "ArrowLeft";
      if (event.key === forward || event.key === "ArrowDown") { step(1); event.preventDefault(); }
      else if (event.key === back || event.key === "ArrowUp") { step(-1); event.preventDefault(); }
      else if (event.key === " ") { step(event.shiftKey ? -1 : 1); event.preventDefault(); }
      else if (event.key === "t") setPanel("contents");
      else if (event.key === "s") setPanel("settings");
      else if (event.key === "f") toggleFullscreen();
      else if (event.key === "+" || event.key === "=") { changeZoom(ZOOM_STEP); event.preventDefault(); }
      else if (event.key === "-") { changeZoom(1 / ZOOM_STEP); event.preventDefault(); }
      else if (event.key === "0") { resetZoom(); event.preventDefault(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panel, settings.direction, step, changeZoom, resetZoom, toggleFullscreen]);

  /** Ctrl and the wheel zooms; a plain wheel is scrolling, which Long Strip needs (§26.10). */
  const onWheel = useCallback((event: React.WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    changeZoom(event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP);
  }, [changeZoom]);

  const spread = (touches: React.TouchList): number | null => {
    if (touches.length < 2) return null;
    const [a, b] = [touches[0]!, touches[1]!];
    return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
  };

  const onTouchStart = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    const first = event.touches[0];
    if (first === undefined) return;
    touch.current = { x: first.clientX, y: first.clientY, spread: spread(event.touches) };
  }, []);

  const onTouchMove = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    const start = touch.current;
    const first = event.touches[0];
    if (start === null || first === undefined) return;
    const pinch = spread(event.touches);
    if (pinch !== null && start.spread !== null && start.spread > 0) {
      setZoom((current) => clampZoom(current * (pinch / start.spread!)));
      touch.current = { ...start, spread: pinch };
      return;
    }
    if (zoom > 1) {      // while zoomed a drag pans, and never turns the page (§26.10)
      setPan((current) => ({ x: current.x + (first.clientX - start.x), y: current.y + (first.clientY - start.y) }));
      touch.current = { ...start, x: first.clientX, y: first.clientY };
    }
  }, [zoom]);

  const onTouchEnd = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    const start = touch.current;
    touch.current = null;
    const last = event.changedTouches[0];
    if (start === null || last === undefined || zoom > 1 || settings.mode === "long_strip") return;
    const travelled = last.clientX - start.x;
    if (Math.abs(travelled) < SWIPE_MIN) { show(); return; }
    const forward = settings.direction === "rtl" ? travelled > 0 : travelled < 0;
    step(forward ? 1 : -1);
  }, [zoom, settings.mode, settings.direction, step, show]);

  const visible = visiblePages(pages, index, settings);

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
        <button type="button" className="reader__button" onClick={toggleFullscreen}>
          {fullscreen ? t("reader.fullscreenExit") : t("reader.fullscreen")}
        </button>
        {/* §26.2: content, reading controls, and everything else behind More. */}
        <button type="button" className="reader__button" aria-expanded={more} aria-controls="reader-more"
                onClick={() => setMore((open) => !open)}>
          {t("reader.more")}
        </button>
        {more && (
          <div className="reader__more" id="reader-more">
            <button type="button" className="reader__button"
                    onClick={() => { void api.post(`/api/reader/units/${id}/mark-read`, {}); setMore(false); }}>
              {t("reader.markRead")}
            </button>
            <button type="button" className="reader__button" onClick={() => changeZoom(ZOOM_STEP)}>
              {t("reader.zoomIn")}
            </button>
            <button type="button" className="reader__button" onClick={() => changeZoom(1 / ZOOM_STEP)}>
              {t("reader.zoomOut")}
            </button>
            <button type="button" className="reader__button" onClick={resetZoom}>{t("reader.zoomReset")}</button>
          </div>
        )}
      </div>

      {/* The pages scroll, so the keyboard must be able to reach them (WCAG 2.1.1). */}
      <div className="reader__stage" data-testid="reader-stage" tabIndex={0} aria-label={t("reader.pages")}
           data-mode={settings.mode}
           data-direction={settings.direction} data-fit={settings.fit} data-zoom={zoom}
           ref={stage} onWheel={onWheel} onDoubleClick={() => (zoom > 1 ? resetZoom() : changeZoom(ZOOM_STEP * 1.6))}
           onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd}
           style={{ "--reader-zoom": zoom, "--reader-pan-x": `${pan.x}px`,
                    "--reader-pan-y": `${pan.y}px` } as React.CSSProperties}>
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

/**
 * Which pages are on screen (§26.7, §26.8).
 *
 * In Double Page the pairing starts after any leading single pages: the cover usually stands alone, and
 * Shift Pairing moves the whole pairing by one for a book with an extra single page in the middle.
 */
function visiblePages(pages: Page[], index: number, settings: ReaderSettings): Page[] {
  if (settings.mode === "long_strip") return pages;
  if (settings.mode !== "double") return pages.slice(index, index + 1);
  const singles = (settings.coverAlone ? 1 : 0) + (settings.shiftPairing ? 1 : 0);
  if (index < singles) return pages.slice(index, index + 1);
  return pages.slice(index, index + 2);
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
