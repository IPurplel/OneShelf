import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import type { Unit, WorkDetails } from "@/api/types";
import { useI18n } from "@/i18n/i18n";
import { languageName } from "@/i18n/language";
import { Icon } from "@/components/Icon";
import { MOBILE_QUERY, useMediaQuery } from "@/app/useMediaQuery";
import { ContentsDrawer } from "./ContentsDrawer";
import { SettingsPanel } from "./SettingsPanel";
import { SourceSwitch } from "./SourceSwitch";
import type { Alternative, Alternatives } from "./SourceSwitch";
import { DEFAULT_SETTINGS, loadSettings, saveSettings } from "./settings";
import type { ReaderSettings } from "./settings";
import { readerLink, workLink } from "./links";
import { useProgress } from "./useProgress";
import { PagePreloads } from "./pagePreloads";

type Page = { index: number; label: string | null; url: string | null };
type PagesResponse = { reading_unit_id: string; pages: Page[] };
type ReaderDefaults = { preload_next: number; preload_previous: number };

/** Until the library answers, the Master's own numbers (§26.18); the registry stays the source. */
const PRELOAD: ReaderDefaults = { preload_next: 15, preload_previous: 4 };

/** A page's height before one has been measured — only ever used to size the spacers (§26.6). */
const ESTIMATED_PAGE = 1200;

const IDLE_MS = 3000;
const ZOOM_STEP = 1.25;
const ZOOM_MIN = 1;
const ZOOM_MAX = 4;
const SWIPE_MIN = 60;

/** §26.24: guidance is one-time. A blocked storage read means it has not been seen, never an error. */
const HINT_KEY = "oneshelf.reader.hint.centre";
const ZONES_HINT_KEY = "oneshelf.reader.hint.zones";
/** A second tap this soon is a double tap (zoom), so a single tap waits this long before acting. */
const TAP_SETTLE_MS = 240;

function hintSeen(key = HINT_KEY): boolean {
  try {
    return window.localStorage.getItem(key) === "seen";
  } catch {
    return false;
  }
}

function rememberHint(key = HINT_KEY): void {
  try {
    window.localStorage.setItem(key, "seen");
  } catch {
    // Remembering is a convenience; the hint simply appears again next time.
  }
}

/** A finger, not a mouse: only there do the page's thirds become buttons. */
function coarsePointer(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && Boolean(window.matchMedia("(pointer: coarse)").matches);
}

/** Typing into a control is not reading: its keys belong to the control. */
function typingInto(target: EventTarget | null): boolean {
  return target instanceof HTMLElement
    && (target.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName));
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
export function ReaderScreen({ unitId, workId, trackId }: { unitId?: string; workId?: string; trackId?: string }) {
  const params = useParams();
  const [search] = useSearchParams();
  const id = unitId ?? params.unitId ?? "";
  const work = workId ?? search.get("work") ?? "";
  const track = trackId ?? search.get("track");
  const { t, language } = useI18n();

  const { data: pageData, error: pageError, reload: reloadPages } = useResource<PagesResponse>(`/api/reader/units/${id}/pages`);
  const { data: details } = useResource<WorkDetails>(`/api/works/${work}`, track ? { track_id: track } : undefined);
  const { data: offer } = useResource<Alternatives>(`/api/reader/units/${id}/alternatives`);
  const { data: readerDefaults } = useResource<ReaderDefaults>("/api/reader/settings");
  const pages = useMemo(() => pageData?.pages ?? [], [pageData]);

  const [settings, setSettings] = useState<ReaderSettings>(DEFAULT_SETTINGS);
  const [panel, setPanel] = useState<null | "contents" | "settings" | "source">(null);
  const [controlsVisible, setControlsVisible] = useState(true);
  const [summoned, setSummoned] = useState(false);
  const [hint, setHint] = useState(false);
  const [loaded, setLoaded] = useState<Set<number>>(new Set());
  const [readyUnit, setReadyUnit] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [atEnd, setAtEnd] = useState(false);
  const [failed, setFailed] = useState<Set<number>>(new Set());
  const [pageRetries, setPageRetries] = useState<Map<number, number>>(new Map());
  const [, rerenderPreloads] = useState(0);
  const preloads = useRef<PagePreloads | null>(null);
  const [skipped, setSkipped] = useState<Set<number>>(new Set());
  const [repairing, setRepairing] = useState(false);
  const [repairProblem, setRepairProblem] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [fullscreen, setFullscreen] = useState(false);
  const [more, setMore] = useState(false);
  const [zonesHint, setZonesHint] = useState(false);
  // A phone gets one compact row of icons; the rarer controls move behind More.
  const compact = useMediaQuery(MOBILE_QUERY);
  const pointerKind = useRef<string>("mouse");
  const pendingTap = useRef<ReturnType<typeof setTimeout> | null>(null);
  const indexRef = useRef(0);
  const stage = useRef<HTMLDivElement | null>(null);
  const touch = useRef<{ x: number; y: number; spread: number | null } | null>(null);
  const { record, flush, stored } = useProgress(id);
  const interacted = useRef(false);
  const engagement = useRef<Promise<unknown>>(Promise.resolve());
  const engage = useCallback((fraction: number) => {
    engagement.current = engagement.current.then(() =>
      api.post(`/api/reader/units/${id}/engagement`, { fraction, interacted: true })).catch(() => {});
  }, [id]);
  const leave = useCallback(() => {
    flush();
    if (work) void engagement.current.then(() => api.post(`/api/reader/works/${work}/leave`, {})).catch(() => {});
  }, [flush, work]);
  useEffect(() => { interacted.current = false; }, [id]);
  const resumed = useRef<string | null>(null);
  const [scrollTo, setScrollTo] = useState<number | null>(null);
  const [pageHeight, setPageHeight] = useState(ESTIMATED_PAGE);
  const heightAnchor = useRef<{ node: HTMLElement; offset: number } | null>(null);
  const navigate = useNavigate();
  const approximate = search.get("approx");

  const units = useMemo(() => details?.units ?? [], [details]);
  const unit = units.find((candidate) => candidate.id === id) ?? null;
  const selectedTrack = details?.tracks.find(candidate => candidate.id === (track ?? details.selected_track_id));
  const canDownload = selectedTrack !== undefined && selectedTrack.can_download !== false;
  const next = nextInSourceOrder(units, id);
  const previous = previousInSourceOrder(units, id);

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
    setRepairProblem(null);
    setPageRetries(new Map());
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
    // A virtualized jump must be immediate: intermediate smooth-scroll events
    // replace the target window while its images are still changing height.
    (target as HTMLElement | null)?.scrollIntoView?.({ block: "start", behavior: "instant" });
    setScrollTo(null);
  }, [scrollTo, index]);

  useLayoutEffect(() => {
    const anchor = heightAnchor.current;
    heightAnchor.current = null;
    const container = stage.current;
    if (!anchor || !container || !container.contains(anchor.node) || settings.mode !== "long_strip") return;
    const offset = anchor.node.getBoundingClientRect().top - container.getBoundingClientRect().top;
    container.scrollTo({ top: container.scrollTop + offset - anchor.offset, behavior: "instant" });
  }, [pageHeight, id, settings.mode]);

  // Interaction reveals the controls in Smart; in Minimal it does not, which is the whole point.
  const show = useCallback(() => {
    if (settings.controls !== "minimal") setControlsVisible(true);
  }, [settings.controls]);

  const summon = useCallback(() => {
    setSummoned(true);
    setControlsVisible(true);
    setHint(false);
  }, []);

  /** Go to one page: the same bookkeeping however the reader got there (keys, taps, scrubber, Home/End). */
  const goTo = useCallback((slot: number) => {
    if (pages.length === 0) return;
    const clamped = Math.min(pages.length - 1, Math.max(0, slot));
    if (settings.mode !== "long_strip" && clamped !== indexRef.current) {
      const nextPages = new Set(visiblePages(pages, clamped, settings).map((page) => page.index));
      setLoaded((current) => new Set([...current].filter((page) => nextPages.has(page))));
    }
    // In Long Strip the page is somewhere down the strip: going to it means scrolling there.
    if (settings.mode === "long_strip" && clamped !== indexRef.current) setScrollTo(clamped);
    indexRef.current = clamped;
    setIndex(clamped);
    setAtEnd(false);
    const fraction = (clamped + 1) / pages.length;
    record(fraction, { page: clamped + 1 });
    engage(fraction);
  }, [pages, settings, record, engage]);

  const step = useCallback((delta: number) => {
    const stride = settings.mode === "double"
      ? Math.max(1, visiblePages(pages, indexRef.current, settings).length) : 1;
    const target = indexRef.current + delta * stride;
    if (pages.length > 0 && target >= pages.length) {
      setAtEnd(true);
      return;
    }
    goTo(Math.max(0, target));
  }, [pages, settings, goTo]);

  const toggleBars = useCallback(() => {
    if (controlsVisible) {
      setControlsVisible(false);
      setSummoned(false);
    } else {
      summon();
    }
  }, [controlsVisible, summon]);

  /**
   * On a touch screen the page's thirds are its buttons: the outer thirds turn the page the way the book
   * reads, the middle shows or hides the bars (§26.5). A second tap close behind is a double tap, which
   * zooms, so a single tap waits a moment before it acts.
   */
  const onStageClick = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    if (pointerKind.current === "mouse" || zoom > 1) return;
    if ((event.target as HTMLElement).closest("button, a, input, label, select, textarea")) return;
    if (pendingTap.current !== null) {
      clearTimeout(pendingTap.current);
      pendingTap.current = null;
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const x = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0.5;
    const side = x < 1 / 3 ? "left" : x > 2 / 3 ? "right" : "middle";
    pendingTap.current = setTimeout(() => {
      pendingTap.current = null;
      setZonesHint(false);
      if (side === "middle" || settings.mode === "long_strip") { toggleBars(); return; }
      const forward = settings.direction === "rtl" ? side === "left" : side === "right";
      step(forward ? 1 : -1);
    }, TAP_SETTLE_MS);
  }, [zoom, settings.mode, settings.direction, step, toggleBars]);

  useEffect(() => () => { if (pendingTap.current !== null) clearTimeout(pendingTap.current); }, []);

  // The thirds are invisible, so a finger is told about them once, the first time it could use them.
  useEffect(() => {
    if (settings.mode === "long_strip" || !coarsePointer() || hintSeen(ZONES_HINT_KEY)) return;
    setZonesHint(true);
    rememberHint(ZONES_HINT_KEY);
    const timer = setTimeout(() => setZonesHint(false), 5000);
    return () => clearTimeout(timer);
  }, [settings.mode]);

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

  /*
   * One window listener for the reader's whole life, calling whatever handler the latest render made. A
   * listener re-subscribed in a passive effect can still hold the previous render's closure when a key
   * arrives right after the pages appear — and that closure has no pages, so the key would do nothing.
   */
  const keyHandler = useRef<(event: KeyboardEvent) => void>(() => {});
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => keyHandler.current(event);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useLayoutEffect(() => {
    keyHandler.current = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setPanel(null); setMore(false); return; }
      if (panel !== null) return;
      // Tab is looking for a control: the bars come back so there is one to find (WCAG 2.4.7).
      if (event.key === "Tab") { if (settings.controls !== "minimal") setControlsVisible(true); return; }
      if (typingInto(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;
      const forward = settings.direction === "rtl" ? "ArrowLeft" : "ArrowRight";
      const back = settings.direction === "rtl" ? "ArrowRight" : "ArrowLeft";
      if (event.key === forward || event.key === "ArrowDown") { step(1); event.preventDefault(); }
      else if (event.key === back || event.key === "ArrowUp") { step(-1); event.preventDefault(); }
      else if (event.key === " ") { step(event.shiftKey ? -1 : 1); event.preventDefault(); }
      else if (event.key === "Home") { goTo(0); event.preventDefault(); }
      else if (event.key === "End") { goTo(pages.length - 1); event.preventDefault(); }
      else if (event.key === "F") toggleFullscreen();
      else if (event.key === "t") setPanel("contents");
      else if (event.key === "s") setPanel("settings");
      else if (event.key === "f") toggleFullscreen();
      // §26.5: download belongs to the reader's own keyboard set, beside the contents and settings keys.
      else if (event.key === "d" && canDownload) void api.post("/api/downloads", { unit_ids: [id] });
      else if (event.key === "+" || event.key === "=") { changeZoom(ZOOM_STEP); event.preventDefault(); }
      else if (event.key === "-") { changeZoom(1 / ZOOM_STEP); event.preventDefault(); }
      else if (event.key === "0") { resetZoom(); event.preventDefault(); }
    };
  });

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
    if (interacted.current) engage((slot + 1) / pages.length);
  }, [settings.mode, pages.length, record, engage]);

  /** Ctrl and the wheel zooms; a plain wheel is scrolling, which Long Strip needs (§26.10). */
  const onWheel = useCallback((event: React.WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey) { interacted.current = true; return; }
    event.preventDefault();
    changeZoom(event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP);
  }, [changeZoom]);

  const spread = (touches: React.TouchList): number | null => {
    if (touches.length < 2) return null;
    const [a, b] = [touches[0]!, touches[1]!];
    return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
  };

  const onTouchStart = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    interacted.current = true;
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
    if (Math.abs(travelled) < SWIPE_MIN) return;          // a tap: the stage's thirds decide what it means
    const forward = settings.direction === "rtl" ? travelled > 0 : travelled < 0;
    step(forward ? 1 : -1);
  }, [zoom, settings.mode, settings.direction, step]);

  /** §26.16: manual, same-language, and never a claim that the pages line up. */
  const openElsewhere = useCallback((alternative: Alternative, position: "start" | "approximate") => {
    if (alternative.unit_id === null) return;
    flush();
    const fraction = position === "approximate" ? `&approx=${stored?.fraction ?? 0}` : "";
    setPanel(null);
    navigate(`${readerLink(alternative.unit_id, work, alternative.track_id)}${fraction}`);
  }, [flush, navigate, stored?.fraction, work]);

  const prevIndex = useRef(index);
  useEffect(() => {
    if (settings.mode === "long_strip" || settings.transition === "instant") {
      prevIndex.current = index;
      return;
    }
    const delta = index - prevIndex.current;
    prevIndex.current = index;
    if (delta === 0) return;
    const el = stage.current;
    if (!el) return;
    const cls = `reader__stage--${settings.transition}-${delta > 0 ? "forward" : "backward"}`;
    el.classList.remove("reader__stage--slide-forward", "reader__stage--slide-backward",
                         "reader__stage--fade-forward", "reader__stage--fade-backward");
    void el.offsetWidth;
    el.classList.add(cls);
    const cleanup = () => el.classList.remove(cls);
    el.addEventListener("animationend", cleanup, { once: true });
    const timer = setTimeout(cleanup, 300);
    return () => { clearTimeout(timer); el.removeEventListener("animationend", cleanup); };
  }, [index, settings.mode, settings.transition]);

  // Reaching the end card is finishing the unit: the last page is recorded as read, the same write as any other.
  useEffect(() => {
    if (!atEnd || pages.length === 0) return;
    record(1, { page: pages.length });
  }, [atEnd, pages.length, record]);

  // Near the end, the next unit's first pages are warmed, so "Read next" opens on a page and not a wait.
  const nearEnd = pages.length > 0 && (atEnd || index >= pages.length - 2);
  const warmed = useRef<string | null>(null);
  const cancelWarm = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (!nearEnd || next === null || warmed.current === next.id) return;
    const timer = setTimeout(() => {
      warmed.current = next.id;
      cancelWarm.current = warmNextUnit(next.id);
    }, 1200);
    return () => clearTimeout(timer);
  }, [nearEnd, next]);
  useEffect(() => () => cancelWarm.current?.(), [id]);

  const progressPct = pages.length > 0 ? ((index + 1) / pages.length) * 100 : 0;

  const preload = readerDefaults ?? PRELOAD;
  const window_ = stripWindow(pages.length, index, preload);
  const visible = settings.mode === "long_strip"
    ? pages.slice(window_.first, window_.last + 1)
    : visiblePages(pages, index, settings);
  const firstSlot = settings.mode === "long_strip" ? window_.first : index;
  const before = settings.mode === "long_strip" ? window_.first : 0;
  const after = settings.mode === "long_strip" ? pages.length - 1 - window_.last : 0;

  useEffect(() => {
    const pool = new PagePreloads(id, () => rerenderPreloads((version) => version + 1));
    preloads.current = pool;
    return () => {
      pool.dispose();
      if (preloads.current === pool) preloads.current = null;
    };
  }, [id]);

  useEffect(() => {
    const pool = preloads.current;
    if (pool?.unitId !== id) return;
    const visibleIndexes = visible.map((page) => page.index);
    const foregroundPage = visible.find((page) => !loaded.has(page.index) && !pool.url(page.index))?.index ?? null;
    if (settings.mode === "long_strip" || readyUnit !== id) {
      pool.update([], visibleIndexes, readyUnit === id ? foregroundPage : null);
      return;
    }
    const band = preloadBand(pages, index, visible.length, preload);
    pool.update(band.map((page) => page.index), visibleIndexes, foregroundPage);
  }, [id, pages, index, visible.length, settings.mode, readyUnit,
      preload.preload_next, preload.preload_previous, loaded]);

  const currentPreloads = preloads.current?.unitId === id ? preloads.current : null;

  return (
    <div className={`reader reader--${settings.background}`} onMouseMove={show}>
      {pages.length > 0 && (
        <div className="reader__scrollProgress" aria-hidden="true"
             style={{ inlineSize: `${progressPct}%` }} />
      )}
      {/* Hidden bars are inert: the keyboard can never land on a control it cannot see (WCAG 2.4.7). */}
      <div role="toolbar" aria-label={t("reader.controls")} className="reader__bar reader__bar--top"
           data-hidden={controlsVisible ? "false" : "true"} inert={!controlsVisible}>
        <Link className="reader__button reader__button--icon" to={workLink(work, track)} onClick={leave}
              aria-label={t("reader.back")} title={t("reader.back")}>
          <span className="reader__icon reader__icon--flip"><Icon name="back" size={20} /></span>
          <span className="reader__label" aria-hidden="true">{t("reader.back")}</span>
        </Link>
        <div className="reader__heading">
          <span className="reader__title" dir="auto" title={details?.work.title ?? ""}>{details?.work.title ?? ""}</span>
          <span className="reader__unit" dir="auto" title={unit?.title ?? ""}>{unit?.title ?? ""}</span>
        </div>
        {/* §26.16: subtle, and about this unit's own track — "English · source-a". */}
        {offer !== null && !compact && (
          <span className="reader__source" data-testid="reader-source" title={t("reader.source")}>
            {languageName(offer.language, language)} · <bdi>{details?.tracks.find((candidate) =>
              candidate.source_id === offer.source_id)?.source_name ?? offer.source_id}</bdi>
          </span>
        )}
        {unit !== null && !compact && (
          <span className={`reader__state reader__state--${unit.downloaded ? "downloaded" : unit.integrity}`}>
            {unit.downloaded ? t("reader.state.downloaded")
              : unit.integrity === "none" ? t("reader.state.notDownloaded")
              : t("reader.state.broken")}
          </span>
        )}
        <button type="button" className="reader__button reader__button--icon" onClick={() => setPanel("contents")}
                aria-label={t("reader.contents")} title={t("reader.contents")}>
          <span className="reader__icon"><Icon name="contents" size={20} /></span>
          <span className="reader__label" aria-hidden="true">{t("reader.contents")}</span>
        </button>
        <button type="button" className="reader__button reader__button--icon" onClick={() => setPanel("settings")}
                aria-label={t("reader.settings")} title={t("reader.settings")}>
          <span className="reader__icon"><Icon name="sliders" size={20} /></span>
          <span className="reader__label" aria-hidden="true">{t("reader.settings")}</span>
        </button>
        {!compact && (
          <button type="button" className="reader__button reader__button--icon" onClick={toggleFullscreen}
                  aria-label={fullscreen ? t("reader.fullscreenExit") : t("reader.fullscreen")}
                  title={fullscreen ? t("reader.fullscreenExit") : t("reader.fullscreen")}>
            <span className="reader__icon"><Icon name={fullscreen ? "fullscreenExit" : "fullscreen"} size={20} /></span>
          </button>
        )}
        {/* §26.2: content, reading controls, and everything else behind More. */}
        <button type="button" className="reader__button reader__button--icon" aria-expanded={more}
                aria-controls="reader-more" aria-label={t("reader.more")} title={t("reader.more")}
                onClick={() => setMore((open) => !open)}>
          <span className="reader__icon"><Icon name="more" size={20} /></span>
        </button>
        {more && (
          <div className="reader__more" id="reader-more">
            {compact && (
              <>
                {(offer !== null || unit !== null) && (
                  <p className="reader__moreStatus">
                    {offer !== null && (
                      <span data-testid="reader-source">
                        {languageName(offer.language, language)} · <bdi>{details?.tracks.find((candidate) =>
                          candidate.source_id === offer.source_id)?.source_name ?? offer.source_id}</bdi>
                      </span>
                    )}
                    {unit !== null && (
                      <span className={`reader__state reader__state--${unit.downloaded ? "downloaded" : unit.integrity}`}>
                        {unit.downloaded ? t("reader.state.downloaded")
                          : unit.integrity === "none" ? t("reader.state.notDownloaded")
                          : t("reader.state.broken")}
                      </span>
                    )}
                  </p>
                )}
                <button type="button" className="reader__button"
                        onClick={() => { toggleFullscreen(); setMore(false); }}>
                  {fullscreen ? t("reader.fullscreenExit") : t("reader.fullscreen")}
                </button>
              </>
            )}
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
            {canDownload && <button type="button" className="reader__button"
                    onClick={() => {
                      void api.post("/api/downloads", { unit_ids: units.map((entry) => entry.id) });
                      setMore(false);
                    }}>
              {t("reader.downloadWork")}
            </button>}
            <button type="button" className="reader__button"
                    onClick={() => { setPanel("source"); setMore(false); }}>
              {t("reader.changeSource")}
            </button>
            <Link className="reader__button" to={workLink(work, track)} onClick={leave}>
              {t("reader.workDetails")}
            </Link>
          </div>
        )}
      </div>

      {/* The pages scroll, so the keyboard must be able to reach them (WCAG 2.1.1). */}
      <div className="reader__stage" data-testid="reader-stage" tabIndex={0} role="region" aria-label={t("reader.pages")}
           data-mode={settings.mode}
           data-direction={settings.direction} data-fit={settings.fit} data-zoom={zoom}
           ref={stage} onPointerDown={(event) => { interacted.current = true; pointerKind.current = event.pointerType || "mouse"; }}
           onClick={onStageClick}
           onWheel={onWheel} onScroll={onScroll} onDoubleClick={() => (zoom > 1 ? resetZoom() : changeZoom(ZOOM_STEP * 1.6))}
           onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd}
           style={{ "--reader-zoom": zoom, "--reader-pan-x": `${pan.x}px`,
                    "--reader-pan-y": `${pan.y}px`,
                    ...(settings.mode === "long_strip" ? { gap: `${settings.gap}px` } : {}) } as React.CSSProperties}>
        {pageError !== null && <>
          <p className="notice notice--problem" role="alert">{pageError === "offline" ? t("state.offline") : pageError}</p>
          <button type="button" className="button" onClick={reloadPages}>{t("reader.retry")}</button>
        </>}
        {repairProblem !== null && <p className="notice notice--problem" role="alert">{repairProblem}</p>}
        {pageData !== null && pageError === null && pages.length === 0 && (
          <div className="reader__failure" role="alert">
            <p>{t("reader.emptyPages")}</p>
            <Link className="button" to={workLink(work, track)} onClick={leave}>{t("reader.backToWork")}</Link>
          </div>
        )}
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
                <button type="button" className="button" onClick={() => {
                  setPageRetries((retries) => new Map(retries).set(page.index, (retries.get(page.index) ?? 0) + 1));
                  setFailed((set) => {
                    const copy = new Set(set);
                    copy.delete(page.index);
                    return copy;
                  });
                }}>{t("reader.retry")}</button>
                {/* Repair is the same download again, through the normal validated commit (§16.5). */}
                {canDownload && <button type="button" className="button" disabled={repairing || unit?.integrity === "none"}
                        onClick={() => {
                          setRepairing(true);
                          setRepairProblem(null);
                          void api.post("/api/downloads", { unit_ids: [id], repair: true })
                            .catch(() => setRepairProblem(t("reader.repairFailed")))
                            .finally(() => setRepairing(false));
                        }}>
                  {t("reader.repair")}
                </button>}
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
                   src={pageRetries.has(page.index)
                     ? `/api/reader/units/${id}/pages/${page.index}?retry=${pageRetries.get(page.index)}`
                     : currentPreloads?.url(page.index) ?? (currentPreloads?.pending(page.index)
                       ? undefined : `/api/reader/units/${id}/pages/${page.index}`)}
                   alt={t("reader.page", { index: page.label ?? page.index })}
                   loading={settings.mode === "long_strip" ? "lazy" : "eager"}
                   fetchPriority={settings.mode === "long_strip" ? "auto" : "high"}
                   onLoad={(event) => {
                     setReadyUnit(id);
                     currentPreloads?.visibleLoaded(page.index);
                     setLoaded((set) => new Set(set).add(page.index));
                     const height = event.currentTarget.getBoundingClientRect().height;
                     // One estimate for the whole strip, updated only when it is materially wrong, so the
                     // spacers and the reserved page heights never disagree.
                     if (height > 0 && Math.abs(height - pageHeight) > 24) {
                       const container = stage.current;
                       const anchor = container?.querySelector<HTMLElement>(`[data-page-slot="${indexRef.current}"]`);
                       if (settings.mode === "long_strip" && container && anchor && heightAnchor.current === null) {
                         heightAnchor.current = { node: anchor,
                           offset: anchor.getBoundingClientRect().top - container.getBoundingClientRect().top };
                       }
                       setPageHeight(height);
                     }
                   }}
                   onError={() => {
                     setFailed((set) => new Set(set).add(page.index));
                   }} />
            </div>
          )
        ))}
        {/* Single and Double keep the same bounded band in memory, without a second image request on page turn. */}
        {after > 0 && (
          <div className="reader__spacer" data-spacer="after" data-pages={after} aria-hidden="true"
               style={{ blockSize: `${after * pageHeight}px` }} />
        )}
        {atEnd && <EndOfUnit unit={unit} next={next} workId={work} trackId={track} onLeave={leave} />}
      </div>

      <div role="toolbar" aria-label={t("reader.progressBar")} className="reader__bar reader__bar--bottom"
           data-hidden={controlsVisible ? "false" : "true"} inert={!controlsVisible}>
        <ChapterLink unit={previous} kind="previous" workId={work} trackId={track} onGo={flush} />
        {/* Numbers read left to right in every language, so "1 / 3" never turns into "3 / 1" in Arabic. */}
        <span className="reader__progress">
          {pages.length > 0 && <bdi dir="ltr">{`${Math.min(index + 1, pages.length)} / ${pages.length}`}</bdi>}
        </span>
        {pages.length > 1 && (
          // The scrubber runs the way the pages run, whatever language the interface is in.
          <input type="range" className="reader__scrubber" aria-label={t("reader.scrubber")}
                 dir={settings.direction === "rtl" ? "rtl" : "ltr"}
                 min={1} max={pages.length} value={Math.min(index + 1, pages.length)}
                 aria-valuemin={1} aria-valuemax={pages.length}
                 aria-valuenow={Math.min(index + 1, pages.length)}
                 onChange={(event) => goTo(Number(event.target.value) - 1)} />
        )}
        <ChapterLink unit={next} kind="next" workId={work} trackId={track} onGo={flush} />
      </div>

      {zonesHint && panel === null && (
        <div className="reader__zones" aria-hidden="true">
          <span className="reader__zone" />
          <span className="reader__zone reader__zone--middle">{t("reader.zonesHint")}</span>
          <span className="reader__zone" />
        </div>
      )}

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

      {panel === "contents" && <ContentsDrawer units={units} currentId={id} workId={work} trackId={track} onClose={() => setPanel(null)} />}
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
  return [...pages.slice(index + onScreen, last + 1), ...pages.slice(first, index).reverse()];
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

function previousInSourceOrder(units: Unit[], currentId: string): Unit | null {
  const ordered = [...units].sort((a, b) => a.order - b.order);
  const position = ordered.findIndex((unit) => unit.id === currentId);
  return position > 0 ? ordered[position - 1]! : null;
}

/** The chapter either side, in Source Track order; a disabled button where there is none, so nothing jumps. */
function ChapterLink({ unit, kind, workId, trackId, onGo }: {
  unit: Unit | null; kind: "previous" | "next"; workId: string; trackId?: string | null; onGo: () => void;
}) {
  const { t } = useI18n();
  const icon = <span className="reader__icon reader__icon--flip">
    <Icon name={kind === "previous" ? "chevronStart" : "chevronEnd"} size={22} /></span>;
  const plain = kind === "previous" ? t("reader.previousChapter") : t("reader.nextChapter");
  if (unit === null) {
    return <button type="button" className="reader__button reader__button--icon" disabled aria-label={plain}
                   title={plain}>{icon}</button>;
  }
  const named = t(kind === "previous" ? "reader.previousChapterNamed" : "reader.nextChapterNamed",
                  { unit: unit.title ?? unit.id });
  return <Link className="reader__button reader__button--icon" to={readerLink(unit.id, workId, trackId)}
               onClick={onGo} aria-label={named} title={named}>{icon}</Link>;
}

/**
 * The end of a unit (§26.13): what comes next, said by name and offered first, and the way back. Reaching
 * it counts as having read the unit, and the next unit's first pages are warmed while this card is read.
 */
function EndOfUnit({ unit, next, workId, trackId, onLeave }: { unit: Unit | null; next: Unit | null; workId: string; trackId?: string | null; onLeave: () => void }) {
  const { t } = useI18n();
  const nextLink = useRef<HTMLAnchorElement>(null);
  // The card arrives as the result of reading on, so the next step is where focus lands.
  useEffect(() => { nextLink.current?.focus({ preventScroll: true }); }, []);
  return (
    <section className="reader__end" role="region" aria-label={t("reader.end", { unit: unit?.title ?? "" })}>
      <p className="reader__endNote">{t("reader.endFinished")}</p>
      <h2 className="reader__endTitle display" dir="auto">{unit?.title ?? ""}</h2>
      {next ? (
        <Link ref={nextLink} className="reader__endNext" to={readerLink(next.id, workId, trackId)}>
          <span className="reader__endNextLabel">{t("reader.readNext")}</span>
          <span className="reader__endNextTitle display" dir="auto">{next.title ?? next.id}</span>
          <span className="reader__icon reader__icon--flip" aria-hidden="true"><Icon name="chevronEnd" size={26} /></span>
        </Link>
      ) : (
        <p className="reader__endNote">{t("reader.endLatest")}</p>
      )}
      <Link className="button button--ghost reader__endBack" to={workLink(workId, trackId)} onClick={onLeave}>
        {t("reader.backToWork")}
      </Link>
    </section>
  );
}

/** Warm the next unit's first pages while this one ends, at the lowest priority the browser offers. */
function warmNextUnit(unitId: string): () => void {
  const controller = new AbortController();
  void fetch(`/api/reader/units/${unitId}/pages`, { signal: controller.signal, credentials: "same-origin",
                                                    priority: "low" } as RequestInit)
    .then((response) => (response.ok ? response.json() as Promise<PagesResponse> : null))
    .then((data) => {
      for (const page of data?.pages.slice(0, 3) ?? []) {
        const image = new Image();
        image.decoding = "async";
        image.src = `/api/reader/units/${unitId}/pages/${page.index}`;
      }
    })
    .catch(() => {});
  return () => controller.abort();
}
