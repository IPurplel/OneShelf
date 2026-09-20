import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import type { Unit, WorkDetails } from "@/api/types";
import { useI18n } from "@/i18n/i18n";
import { languageName } from "@/i18n/language";
import { ContentsDrawer } from "./ContentsDrawer";
import { SettingsPanel } from "./SettingsPanel";
import { SourceSwitch } from "./SourceSwitch";
import type { Alternative, Alternatives } from "./SourceSwitch";
import { DEFAULT_SETTINGS, loadSettings, saveSettings } from "./settings";
import type { ReaderSettings } from "./settings";
import { useProgress } from "./useProgress";

type Page = { index: number; label: string | null; url: string | null };
type PagesResponse = { reading_unit_id: string; pages: Page[] };
type ReaderDefaults = { preload_next: number; preload_previous: number };

/** Until the library answers, the Master's own numbers (§26.18); the registry stays the source. */
const PRELOAD: ReaderDefaults = { preload_next: 7, preload_previous: 4 };

/** A page's height before one has been measured — only ever used to size the spacers (§26.6). */
const ESTIMATED_PAGE = 1200;

const IDLE_MS = 3000;
const ZOOM_STEP = 1.25;
const ZOOM_MIN = 1;
const ZOOM_MAX = 4;
const SWIPE_MIN = 60;

/** §26.24: guidance is one-time. A blocked storage read means it has not been seen, never an error. */
const HINT_KEY = "oneshelf.reader.hint.centre";

function hintSeen(): boolean {
  try {
    return window.localStorage.getItem(HINT_KEY) === "seen";
  } catch {
    return false;
  }
}

function rememberHint(): void {
  try {
    window.localStorage.setItem(HINT_KEY, "seen");
  } catch {
    // Remembering is a convenience; the hint simply appears again next time.
  }
}

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
  const { data: offer } = useResource<Alternatives>(`/api/reader/units/${id}/alternatives`);
  const { data: readerDefaults } = useResource<ReaderDefaults>("/api/reader/settings");
  const pages = useMemo(() => pageData?.pages ?? [], [pageData]);

  const [settings, setSettings] = useState<ReaderSettings>(DEFAULT_SETTINGS);
  const [panel, setPanel] = useState<null | "contents" | "settings" | "source">(null);
  const [controlsVisible, setControlsVisible] = useState(true);
  const [summoned, setSummoned] = useState(false);
  const [hint, setHint] = useState(false);
  const [loaded, setLoaded] = useState<Set<number>>(new Set());
  const [index, setIndex] = useState(0);
  const [atEnd, setAtEnd] = useState(false);
  const [failed, setFailed] = useState<Set<number>>(new Set());
  const [skipped, setSkipped] = useState<Set<number>>(new Set());
  const [repairing, setRepairing] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [fullscreen, setFullscreen] = useState(false);
  const [more, setMore] = useState(false);
  const indexRef = useRef(0);
  const stage = useRef<HTMLDivElement | null>(null);
  const touch = useRef<{ x: number; y: number; spread: number | null } | null>(null);
  const { record, flush, stored } = useProgress(id);
  const resumed = useRef<string | null>(null);
  const [scrollTo, setScrollTo] = useState<number | null>(null);
  const [pageHeight, setPageHeight] = useState(ESTIMATED_PAGE);
  const navigate = useNavigate();
  const approximate = search.get("approx");

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

  /**
   * Controls auto-hide when idle, and never while a panel is open (§26.3).
   *
   * Minimal goes further: the bars start hidden and stay hidden until they are summoned, so a drifting
   * mouse cannot bring them back — only the centre zone, its keyboard equivalent, or opening a panel.
   */
  useEffect(() => {
    if (panel !== null || more) {
      setControlsVisible(true);
      return;
    }
    if (settings.controls === "minimal" && !summoned) {
      setControlsVisible(false);
      if (!hintSeen()) {
        setHint(true);
        rememberHint();
      }
      return;
    }
    if (!controlsVisible) return;
    const timer = setTimeout(() => {
      setControlsVisible(false);
      setSummoned(false);
    }, IDLE_MS);
    return () => clearTimeout(timer);
  }, [panel, more, controlsVisible, index, settings.controls, summoned]);

  /**
   * One reader serves every unit, so what belongs to a unit leaves with it.
   *
   * The route keeps this component mounted while the unit changes, and page-level state that outlived
   * its unit showed the previous chapter's failures and its end-of-unit card over a chapter that had
   * only just opened (I-20).
   */
  useEffect(() => {
    setFailed(new Set());
    setSkipped(new Set());
    setLoaded(new Set());
    setAtEnd(false);
    // A new unit starts at its own beginning; where it is resumed to is decided by the library, below.
    indexRef.current = 0;
    setIndex(0);
    setPanel(null);
    setMore(false);
  }, [id]);

  /**
   * Resume where this unit was left (§26.15).
   *
   * The position comes from the library, so it is the same on every device; it is read once per unit and
   * writes nothing, which is what keeps a resume from overwriting a newer tab (§26.23). A locator from an
   * older catalog can point past the end, so it is clamped rather than trusted.
   */
  useEffect(() => {
    if (stored === null || pages.length === 0 || resumed.current === id) return;
    resumed.current = id;
    // Arriving from another source: the position is the fraction that was read there, applied to this
    // unit's own length. It is approximate, it says so on screen, and no page is matched to any page.
    if (approximate !== null) {
      const fraction = Math.min(1, Math.max(0, Number(approximate)));
      if (Number.isFinite(fraction)) {
        const target = Math.min(Math.round(fraction * (pages.length - 1)), pages.length - 1);
        indexRef.current = target;
        setIndex(target);
        if (target > 0) setScrollTo(target);
        return;
      }
    }
    const locator = stored.locator as { page?: number } | null;
    const page = typeof locator?.page === "number" ? locator.page : 1;
    const slot = Math.min(Math.max(0, page - 1), pages.length - 1);
    if (slot === 0) return;
    indexRef.current = slot;
    setIndex(slot);
    setScrollTo(slot);
  }, [stored, pages.length, id, approximate]);

  // In Long Strip every page is on screen, so resuming means bringing that page into view.
  useEffect(() => {
    if (scrollTo === null) return;
    const target = stage.current?.querySelector(`[data-page-slot="${scrollTo}"]`);
    // The resume needs no guard against its own scroll: the position is read from the pages, so the
    // scroll it causes resolves to the slot that was just restored and changes nothing.
    (target as HTMLElement | null)?.scrollIntoView?.({ block: "start" });
    setScrollTo(null);
  }, [scrollTo, index]);

  // Interaction reveals the controls in Smart; in Minimal it does not, which is the whole point.
  const show = useCallback(() => {
    if (settings.controls !== "minimal") setControlsVisible(true);
  }, [settings.controls]);

  const summon = useCallback(() => {
    setSummoned(true);
    setControlsVisible(true);
    setHint(false);
  }, []);

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

  /**
   * In Long Strip the reader's position is where they have scrolled to (§26.6, §26.11). It drives the
   * window, and it records progress through the same debounced, revision-carrying write as every other
   * mode, so nothing about §26.23 changes.
   */
  const onScroll = useCallback(() => {
    const node = stage.current;
    if (node === null || settings.mode !== "long_strip" || pages.length === 0) return;
    const slot = scrolledSlot(node, pages.length);
    if (slot === null || slot === indexRef.current) return;
    indexRef.current = slot;
    setIndex(slot);
    record((slot + 1) / pages.length, { page: slot + 1 });
  }, [settings.mode, pages.length, record]);

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

  /** §26.16: manual, same-language, and never a claim that the pages line up. */
  const openElsewhere = useCallback((alternative: Alternative, position: "start" | "approximate") => {
    if (alternative.unit_id === null) return;
    flush();
    const fraction = position === "approximate" ? `&approx=${stored?.fraction ?? 0}` : "";
    setPanel(null);
    navigate(`/read/${alternative.unit_id}?work=${work}${fraction}`);
  }, [flush, navigate, stored?.fraction, work]);

  const preload = readerDefaults ?? PRELOAD;
  const window_ = stripWindow(pages.length, index, preload);
  const visible = settings.mode === "long_strip"
    ? pages.slice(window_.first, window_.last + 1)
    : visiblePages(pages, index, settings);
  const firstSlot = settings.mode === "long_strip" ? window_.first : index;
  const before = settings.mode === "long_strip" ? window_.first : 0;
  const after = settings.mode === "long_strip" ? pages.length - 1 - window_.last : 0;

  return (
    <div className={`reader reader--${settings.background}`} onMouseMove={show}>
      <div role="toolbar" aria-label={t("reader.controls")} className="reader__bar reader__bar--top"
           data-hidden={controlsVisible ? "false" : "true"}>
        <Link className="reader__button" to={work ? `/works/${work}` : "/shelf"} onClick={flush}>
          {t("reader.back")}
        </Link>
        <span className="reader__title">{details?.work.title ?? ""}</span>
        <span className="reader__unit">{unit?.title ?? ""}</span>
        {/* §26.16: subtle, and about this unit's own track — "English · source-a". */}
        {offer !== null && (
          <span className="reader__source" data-testid="reader-source" title={t("reader.source")}>
            {languageName(offer.language)} · {offer.source_id}
          </span>
        )}
        <button type="button" className="reader__button" onClick={() => setPanel("contents")}>
          {t("reader.contents")}
        </button>
        <button type="button" className="reader__button" onClick={() => setPanel("settings")}>
          {t("reader.settings")}
        </button>
        {unit !== null && (
          <span className={`reader__state reader__state--${unit.downloaded ? "downloaded" : unit.integrity}`}>
            {unit.downloaded ? t("reader.state.downloaded")
              : unit.integrity === "none" ? t("reader.state.notDownloaded")
              : t("reader.state.broken")}
          </span>
        )}
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
            <button type="button" className="reader__button"
                    onClick={() => { void api.post(`/api/reader/units/${id}/mark-unread`, {}); setMore(false); }}>
              {t("reader.markUnread")}
            </button>
            <button type="button" className="reader__button"
                    onClick={() => {
                      void api.post("/api/downloads", { unit_ids: units.map((entry) => entry.id) });
                      setMore(false);
                    }}>
              {t("reader.downloadWork")}
            </button>
            <button type="button" className="reader__button"
                    onClick={() => { setPanel("source"); setMore(false); }}>
              {t("reader.changeSource")}
            </button>
            <Link className="reader__button" to={work ? `/works/${work}` : "/shelf"} onClick={flush}>
              {t("reader.workDetails")}
            </Link>
          </div>
        )}
      </div>

      {/* The pages scroll, so the keyboard must be able to reach them (WCAG 2.1.1). */}
      <div className="reader__stage" data-testid="reader-stage" tabIndex={0} aria-label={t("reader.pages")}
           data-mode={settings.mode}
           data-direction={settings.direction} data-fit={settings.fit} data-zoom={zoom}
           ref={stage} onWheel={onWheel} onScroll={onScroll} onDoubleClick={() => (zoom > 1 ? resetZoom() : changeZoom(ZOOM_STEP * 1.6))}
           onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd}
           style={{ "--reader-zoom": zoom, "--reader-pan-x": `${pan.x}px`,
                    "--reader-pan-y": `${pan.y}px` } as React.CSSProperties}>
        {pageError !== null && <p className="notice notice--problem" role="alert">{t("state.offline")}</p>}
        {before > 0 && (
          <div className="reader__spacer" data-spacer="before" data-pages={before} aria-hidden="true"
               style={{ blockSize: `${before * pageHeight}px` }} />
        )}
        {visible.map((page, offset) => (
          skipped.has(page.index) ? (
            <div key={page.index} className="reader__skipped" aria-hidden="true" />
          ) : failed.has(page.index) ? (
            <div key={page.index} className="reader__failed" role="group" aria-label={t("reader.pageFailed")}>
              <p>{t("reader.pageFailed")}</p>
              <p className="cards__meta">{t("reader.pageFailedHelp")}</p>
              <div className="firstrun__actions">
                <button type="button" className="button" onClick={() => setFailed((set) => {
                  const copy = new Set(set);
                  copy.delete(page.index);
                  return copy;
                })}>{t("reader.retry")}</button>
                {/* Repair is the same download again, through the normal validated commit (§16.5). */}
                <button type="button" className="button" disabled={repairing || unit?.integrity === "none"}
                        onClick={() => {
                          setRepairing(true);
                          void api.post("/api/downloads", { unit_ids: [id], repair: true })
                            .finally(() => setRepairing(false));
                        }}>
                  {t("reader.repair")}
                </button>
                <button type="button" className="button"
                        onClick={() => setSkipped((set) => new Set(set).add(page.index))}>
                  {t("reader.skip")}
                </button>
              </div>
            </div>
          ) : (
            <div key={page.index} data-page={page.index} data-page-slot={firstSlot + offset}
                 data-loaded={loaded.has(page.index) ? "true" : "false"}
                 /* §26.24: the page keeps its place while it loads, so nothing under it moves. */
                 className={`reader__frame${loaded.has(page.index) ? "" : " reader__page--skeleton"}`}
                 style={settings.mode === "long_strip" ? { minBlockSize: `${pageHeight}px` } : undefined}>
              <img className="reader__page"
                   src={`/api/reader/units/${id}/pages/${page.index}`}
                   alt={t("reader.page", { index: page.label ?? page.index })} loading="lazy"
                   onLoad={(event) => {
                     setLoaded((set) => new Set(set).add(page.index));
                     const height = event.currentTarget.getBoundingClientRect().height;
                     // One estimate for the whole strip, updated only when it is materially wrong, so the
                     // spacers and the reserved page heights never disagree.
                     if (height > 0 && Math.abs(height - pageHeight) > 24) setPageHeight(height);
                   }}
                   onError={() => setFailed((set) => new Set(set).add(page.index))} />
            </div>
          )
        ))}
        {/*
          * §26.18: in Single and Double the band around the page is fetched quietly — the next seven and
          * the previous four — so a page turn is instant without ever putting those pages on screen.
          * Long Strip needs none of this: its window already mounts the same band.
          */}
        {settings.mode !== "long_strip" && preloadBand(pages, index, visible.length, preload).map((page) => (
          <img key={`preload-${page.index}`} className="reader__preload" data-preload="true" aria-hidden="true"
               alt="" src={`/api/reader/units/${id}/pages/${page.index}`} loading="eager" decoding="async" />
        ))}
        {after > 0 && (
          <div className="reader__spacer" data-spacer="after" data-pages={after} aria-hidden="true"
               style={{ blockSize: `${after * pageHeight}px` }} />
        )}
        {atEnd && <EndOfUnit unit={unit} next={next} workId={work} />}
      </div>

      <div role="toolbar" aria-label={t("reader.progressBar")} className="reader__bar reader__bar--bottom"
           data-hidden={controlsVisible ? "false" : "true"}>
        <span className="reader__progress">
          {pages.length > 0 ? `${Math.min(index + 1, pages.length)} / ${pages.length}` : ""}
        </span>
        {pages.length > 1 && (
          <input type="range" className="reader__scrubber" aria-label={t("reader.scrubber")}
                 dir={settings.direction === "rtl" ? "rtl" : "ltr"}
                 min={1} max={pages.length} value={Math.min(index + 1, pages.length)}
                 aria-valuemin={1} aria-valuemax={pages.length}
                 aria-valuenow={Math.min(index + 1, pages.length)}
                 onChange={(event) => {
                   const slot = Number(event.target.value) - 1;
                   indexRef.current = slot;
                   setIndex(slot);
                   setScrollTo(slot);
                   record((slot + 1) / pages.length, { page: slot + 1 });
                 }} />
        )}
      </div>

      {/*
        * §26.3b: in Minimal the bars stay away until they are summoned, so the way back to them is a
        * real control — the centre zone the hint names, reachable by pointer and by keyboard alike.
        */}
      {settings.controls === "minimal" && !controlsVisible && panel === null && (
        <button type="button" className="reader__summon" onClick={summon} aria-label={t("reader.showControls")}>
          {hint && <span className="reader__hint">{t("reader.hint")}</span>}
        </button>
      )}
      {approximate !== null && (
        <p className="notice notice--info reader__approximate" role="status">{t("reader.approximatePosition")}</p>
      )}

      {panel === "contents" && <ContentsDrawer units={units} currentId={id} workId={work} onClose={() => setPanel(null)} />}
      {panel === "settings" && (
        <SettingsPanel settings={settings} onChange={changeSettings} onClose={() => setPanel(null)} />
      )}
      {panel === "source" && offer !== null && (
        <SourceSwitch offer={offer} workId={work} onClose={() => setPanel(null)}
                      onStart={(alternative) => openElsewhere(alternative, "start")}
                      onApproximate={(alternative) => openElsewhere(alternative, "approximate")} />
      )}
    </div>
  );
}

/**
 * Where the reader is, in Long Strip (§26.6).
 *
 * The mounted pages are asked where they are, because a chapter's pages are not all the same height and
 * an average would put the reader somewhere they are not — and, after a resume, could shift the window
 * away from the page they asked for. Only when there is no layout at all does this fall back to the
 * scroll fraction, which is the same approximation the spacers are built on.
 */
function scrolledSlot(stage: HTMLElement, count: number): number | null {
  const top = stage.getBoundingClientRect().top;
  for (const node of stage.querySelectorAll<HTMLElement>("[data-page-slot]")) {
    const rect = node.getBoundingClientRect();
    if (rect.height > 0 && rect.bottom > top + 1) return Number(node.dataset.pageSlot);
  }
  const travel = stage.scrollHeight - stage.clientHeight;
  if (travel <= 0) return null;
  const fraction = Math.min(1, Math.max(0, stage.scrollTop / travel));
  return Math.min(count - 1, Math.round(fraction * (count - 1)));
}

/**
 * The bounded window Long Strip keeps around the reader (§26.6, §26.18).
 *
 * Only these pages are mounted, so a three-hundred-page chapter is never held whole, and the band is
 * exactly the preload the Master asks for: the next seven and the previous four.
 */
function stripWindow(count: number, index: number, preload: ReaderDefaults): { first: number; last: number } {
  if (count === 0) return { first: 0, last: -1 };
  return {
    first: Math.max(0, index - preload.preload_previous),
    last: Math.min(count - 1, index + preload.preload_next),
  };
}

/** The pages fetched around what is on screen, never mounted into the reading flow (§26.18). */
function preloadBand(pages: Page[], index: number, onScreen: number, preload: ReaderDefaults): Page[] {
  const first = Math.max(0, index - preload.preload_previous);
  const last = Math.min(pages.length - 1, index + onScreen - 1 + preload.preload_next);
  return pages.slice(first, last + 1).filter((_, offset) => {
    const slot = first + offset;
    return slot < index || slot >= index + onScreen;
  });
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
