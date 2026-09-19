/** Master §26.1–26.24, §27: the Sequential Reader. Local reading needs no source, plugin or network. */
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReaderScreen } from "./ReaderScreen";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

const PAGES = {
  reading_unit_id: "u2",
  pages: [
    { index: 1, label: "1", url: null },
    { index: 2, label: "2", url: null },
    { index: 3, label: "3", url: null },
  ],
};

const LONG = {
  reading_unit_id: "u2",
  pages: Array.from({ length: 60 }, (_, i) => ({ index: i + 1, label: String(i + 1), url: null })),
};

const READER_SETTINGS = {
  auto_mark_read_threshold: 0.97, smart_controls_hide_after_ms: 3000, remember_per_work: true,
  preload_next: 7, preload_previous: 4,
};

const WORK = {
  work: { id: "w1", title: "The Irregular Chronicle", original_title: null, creator: null, description: null,
          content_type: "manga", content_type_source: "source", aliases: [] },
  shelf: { on_shelf: true, favorite: false, pinned: false, completed: false },
  follow: { following: false, preferred_source_id: null, track_id: null, language: null, last_successful_at: null },
  tracks: [{ id: "t1", source_id: "local", language: "en", kind: "local", availability: "available", unit_count: 3 }],
  selected_track_id: "t1",
  units: [
    { id: "u1", title: "Prologue", number: null, unit_type: "prologue", volume: null, order: 1, release_date: null,
      availability: "available", url: null, downloaded: true, formats: ["cbz"], read_state: "read", fraction: 1,
      read_at: null },
    { id: "u2", title: "Chapter 1", number: "1", unit_type: "chapter", volume: null, order: 2, release_date: null,
      availability: "available", url: null, downloaded: true, formats: ["cbz"], read_state: "unread", fraction: 0,
      read_at: null },
    { id: "u3", title: "Special", number: null, unit_type: "special", volume: null, order: 3, release_date: null,
      availability: "available", url: null, downloaded: true, formats: ["cbz"], read_state: "unread", fraction: 0,
      read_at: null },
  ],
  continue_unit_id: "u2",
};

const PROGRESS = { read_state: "unread", fraction: 0, locator: null, revision: 0 };

function stub(extra: ReturnType<typeof get>[] = [], progress: Record<string, unknown> = PROGRESS) {
  return mockApi([
    get("/api/reader/units/u2/pages", PAGES),
    get("/api/reader/units/u2/progress", progress),
    get("/api/works/w1", WORK),
    get("/api/reader/settings", READER_SETTINGS),
    post("/api/reader/units/u2/progress", { ...PROGRESS, revision: 1, read_state: "partial" }),
    post("/api/reader/units/u2/mark-read", { ...PROGRESS, revision: 1, read_state: "read" }),
    ...extra,
  ]);
}

let restoreScroll: (() => void) | null = null;

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => {
  restoreScroll?.();
  restoreScroll = null;
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Sequential Reader", () => {
  it("reads local pages without asking any source", async () => {
    const calls = stub();
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);

    const pages = await screen.findAllByRole("img", { name: /page \d/i });
    expect(pages).toHaveLength(3);
    expect(pages[0]).toHaveAttribute("src", "/api/reader/units/u2/pages/1");
    expect(calls.every((call) => call.url.startsWith("/api/reader") || call.url.startsWith("/api/works"))).toBe(true);
  });

  it("offers the three sequential modes and remembers the choice for this work", async () => {
    stub();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await user.click(screen.getByRole("button", { name: /reader settings/i }));
    const panel = screen.getByRole("dialog", { name: /reader settings/i });
    const modes = within(panel).getByRole("radiogroup", { name: /mode/i });
    expect(within(modes).getAllByRole("radio").map((r) => r.getAttribute("value")))
      .toEqual(["long_strip", "single", "double"]);

    await user.click(within(modes).getByRole("radio", { name: /double/i }));
    expect(screen.getByTestId("reader-stage")).toHaveAttribute("data-mode", "double");
  });

  it("respects reading direction rather than assuming left to right", async () => {
    stub();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await user.click(screen.getByRole("button", { name: /reader settings/i }));
    const panel = screen.getByRole("dialog", { name: /reader settings/i });
    await user.click(within(panel).getByRole("radio", { name: /right to left/i }));
    expect(screen.getByTestId("reader-stage")).toHaveAttribute("data-direction", "rtl");
  });

  it("keeps controls visible while a panel is open, and hides them when idle", async () => {
    stub();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    expect(screen.getByRole("toolbar", { name: /reading controls/i })).toBeVisible();
    await user.click(screen.getByRole("button", { name: /contents/i }));
    act(() => { vi.advanceTimersByTime(6000); });
    expect(screen.getByRole("toolbar", { name: /reading controls/i })).toBeVisible();   // a panel is open

    await user.keyboard("{Escape}");
    act(() => { vi.advanceTimersByTime(4000); });
    expect(screen.getByRole("toolbar", { name: /reading controls/i })).toHaveAttribute("data-hidden", "true");
  });

  it("writes progress once the reader settles, carrying the revision it last saw", async () => {
    const calls = stub();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await user.keyboard("{ArrowRight}");
    act(() => { vi.advanceTimersByTime(1500); });

    const write = calls.find((call) => call.method === "POST" && call.url.endsWith("/progress"));
    expect(write).toBeDefined();
    expect((write!.body as { revision: number }).revision).toBe(0);
  });

  it("flushes progress when the tab is hidden", async () => {
    const calls = stub();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });
    await user.keyboard("{ArrowRight}");

    act(() => {
      Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(calls.some((call) => call.method === "POST" && call.url.endsWith("/progress"))).toBe(true);
  });

  it("ends the unit with the next unit in source order, never chapter plus one", async () => {
    stub();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");
    const card = await screen.findByRole("region", { name: /end of/i });
    expect(within(card).getByRole("link", { name: /special/i })).toHaveAttribute("href", "/read/u3?work=w1");
    expect(within(card).getByRole("link", { name: /back to/i })).toHaveAttribute("href", "/works/w1");
  });

  it("shows the reading units and their states in the contents drawer", async () => {
    stub();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await user.click(screen.getByRole("button", { name: /contents/i }));
    const drawer = screen.getByRole("dialog", { name: /contents/i });
    const items = await within(drawer).findAllByRole("listitem");
    expect(items.map((i) => i.textContent)).toEqual([
      expect.stringContaining("Prologue"), expect.stringContaining("Chapter 1"), expect.stringContaining("Special"),
    ]);
    expect(within(drawer).getByRole("link", { current: true })).toHaveTextContent("Chapter 1");
  });

  it("pairs a double-page spread from the cover, and shifts the pairing when the book needs it", async () => {
    stub();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await user.click(screen.getByRole("button", { name: /reader settings/i }));
    const panel = screen.getByRole("dialog", { name: /reader settings/i });
    await user.click(within(panel).getByRole("radio", { name: /double/i }));
    await user.keyboard("{Escape}");

    // The cover stands alone by default, so the spreads that follow line up (§26.8).
    expect(screen.getAllByRole("img", { name: /page \d/i })).toHaveLength(1);
    await user.keyboard("{ArrowRight}");
    expect(screen.getAllByRole("img", { name: /page \d/i }).map((img) => img.getAttribute("src")))
      .toEqual(["/api/reader/units/u2/pages/2", "/api/reader/units/u2/pages/3"]);

    await user.click(screen.getByRole("button", { name: /reader settings/i }));
    await user.click(within(screen.getByRole("dialog", { name: /reader settings/i }))
      .getByRole("checkbox", { name: /first page alone/i }));
    await user.keyboard("{Escape}");
    await user.keyboard("{ArrowLeft}");
    expect(screen.getAllByRole("img", { name: /page \d/i }).map((img) => img.getAttribute("src")))
      .toEqual(["/api/reader/units/u2/pages/1", "/api/reader/units/u2/pages/2"]);

    await user.click(screen.getByRole("button", { name: /reader settings/i }));
    await user.click(within(screen.getByRole("dialog", { name: /reader settings/i }))
      .getByRole("checkbox", { name: /shift the pairing/i }));
    await user.keyboard("{Escape}");
    expect(screen.getAllByRole("img", { name: /page \d/i })).toHaveLength(1);       // pairing moved by one
  });

  it("zooms from the keyboard and with Ctrl and the wheel, and resets to the fit", async () => {
    stub();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });
    const stage = screen.getByTestId("reader-stage");
    expect(stage).toHaveAttribute("data-zoom", "1");

    await user.keyboard("+");
    expect(Number(stage.getAttribute("data-zoom"))).toBeGreaterThan(1);
    await user.keyboard("0");
    expect(stage).toHaveAttribute("data-zoom", "1");

    fireEvent.wheel(stage, { deltaY: -120, ctrlKey: true });
    expect(Number(stage.getAttribute("data-zoom"))).toBeGreaterThan(1);

    fireEvent.wheel(stage, { deltaY: -120 });                       // a plain wheel is scrolling, not zooming
    const afterScroll = stage.getAttribute("data-zoom");
    fireEvent.wheel(stage, { deltaY: -120 });
    expect(stage).toHaveAttribute("data-zoom", afterScroll!);
  });

  it("zooms on a double tap and pans instead of turning the page while zoomed", async () => {
    stub();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    // A horizontal swipe turns the page where that is what a swipe means: Long Strip scrolls instead.
    await user.click(screen.getByRole("button", { name: /reader settings/i }));
    await user.click(within(screen.getByRole("dialog", { name: /reader settings/i }))
      .getByRole("radio", { name: /single/i }));
    await user.keyboard("{Escape}");
    const stage = screen.getByTestId("reader-stage");

    fireEvent.doubleClick(stage);
    expect(Number(stage.getAttribute("data-zoom"))).toBeGreaterThan(1);

    // A swipe while zoomed pans the page; it must not also turn it (§26.10).
    fireEvent.touchStart(stage, { touches: [{ clientX: 200, clientY: 200 }] });
    fireEvent.touchMove(stage, { touches: [{ clientX: 60, clientY: 200 }] });
    fireEvent.touchEnd(stage, { changedTouches: [{ clientX: 60, clientY: 200 }] });
    expect(screen.getByRole("toolbar", { name: /reading progress/i })).toHaveTextContent("1 / 3");

    fireEvent.doubleClick(stage);
    expect(stage).toHaveAttribute("data-zoom", "1");
    fireEvent.touchStart(stage, { touches: [{ clientX: 200, clientY: 200 }] });
    fireEvent.touchMove(stage, { touches: [{ clientX: 60, clientY: 200 }] });
    fireEvent.touchEnd(stage, { changedTouches: [{ clientX: 60, clientY: 200 }] });
    expect(screen.getByRole("toolbar", { name: /reading progress/i })).toHaveTextContent("2 / 3");
  });

  it("goes fullscreen when asked, and says so", async () => {
    stub();
    const request = vi.fn(() => Promise.resolve());
    const exit = vi.fn(() => Promise.resolve());
    Object.defineProperty(Element.prototype, "requestFullscreen", { value: request, configurable: true });
    Object.defineProperty(document, "exitFullscreen", { value: exit, configurable: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await user.click(screen.getByRole("button", { name: /full screen/i }));
    expect(request).toHaveBeenCalled();

    Object.defineProperty(document, "fullscreenElement", { value: screen.getByTestId("reader-stage"),
                                                           configurable: true });
    act(() => { document.dispatchEvent(new Event("fullscreenchange")); });
    await user.keyboard("f");
    expect(exit).toHaveBeenCalled();
  });

  it("keeps the reading controls to three layers, with the rest behind More", async () => {
    stub();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    const bar = screen.getByRole("toolbar", { name: /reading controls/i });
    expect(within(bar).queryByRole("button", { name: /mark as read/i })).not.toBeInTheDocument();
    expect(within(bar).queryByRole("button", { name: /zoom in/i })).not.toBeInTheDocument();

    const more = within(bar).getByRole("button", { name: /more/i });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await user.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    expect(within(bar).getByRole("button", { name: /mark as read/i })).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: /zoom in/i })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(within(bar).queryByRole("button", { name: /mark as read/i })).not.toBeInTheDocument();
  });

  it("fits a page to the reading area rather than leaving it at its own pixel size", async () => {
    stub();
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });
    expect(screen.getByTestId("reader-stage")).toHaveAttribute("data-fit", "smart");
  });

  it("carries the revision the library already holds, so the first write is not stale", async () => {
    const calls = mockApi([
      get("/api/reader/units/u2/pages", PAGES),
      get("/api/reader/units/u2/progress", { ...PROGRESS, revision: 3, fraction: 0.4, read_state: "partial" }),
      get("/api/works/w1", WORK),
    get("/api/reader/settings", READER_SETTINGS),
      post("/api/reader/units/u2/progress", { ...PROGRESS, revision: 4, read_state: "partial" }),
    ]);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await user.keyboard("{ArrowRight}");
    act(() => { vi.advanceTimersByTime(1500); });

    const write = calls.find((call) => call.method === "POST" && call.url.endsWith("/progress"));
    expect((write!.body as { revision: number }).revision).toBe(3);
  });

  it("lets the keyboard reach the pages themselves, which scroll", async () => {
    stub();
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    const stage = screen.getByTestId("reader-stage");
    expect(stage).toHaveAttribute("tabindex", "0");
    expect(stage).toHaveAccessibleName();
  });

  it("opens a unit where it was left rather than at the beginning", async () => {
    stub([], { ...PROGRESS, read_state: "partial", fraction: 0.66, locator: { page: 2 }, revision: 4 });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await waitFor(() =>
      expect(screen.getByRole("toolbar", { name: /reading progress/i })).toHaveTextContent("2 / 3"));
  });

  it("brings the stored page into view in Long Strip, where every page is on screen", async () => {
    const scrollIntoView = vi.fn();
    const previous = Object.getOwnPropertyDescriptor(Element.prototype, "scrollIntoView");
    Object.defineProperty(Element.prototype, "scrollIntoView", { value: scrollIntoView, configurable: true });
    restoreScroll = () => {
      if (previous) Object.defineProperty(Element.prototype, "scrollIntoView", previous);
      else delete (Element.prototype as unknown as Record<string, unknown>).scrollIntoView;
    };
    stub([], { ...PROGRESS, read_state: "partial", fraction: 0.66, locator: { page: 3 }, revision: 2 });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
    const scrolled = scrollIntoView.mock.instances[0] as HTMLElement;
    expect(scrolled.getAttribute("src")).toBe("/api/reader/units/u2/pages/3");
  });

  it("clamps a stored position that is past the end of the unit", async () => {
    stub([], { ...PROGRESS, read_state: "partial", fraction: 1, locator: { page: 99 }, revision: 1 });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await waitFor(() =>
      expect(screen.getByRole("toolbar", { name: /reading progress/i })).toHaveTextContent("3 / 3"));
  });

  it("starts at the beginning when the library holds no position", async () => {
    stub();
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });
    expect(screen.getByRole("toolbar", { name: /reading progress/i })).toHaveTextContent("1 / 3");
  });

  it("writes nothing merely by resuming, so a newer tab is never overwritten", async () => {
    const calls = stub([], { ...PROGRESS, read_state: "partial", fraction: 0.66, locator: { page: 2 },
                             revision: 4 });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });
    await waitFor(() =>
      expect(screen.getByRole("toolbar", { name: /reading progress/i })).toHaveTextContent("2 / 3"));

    act(() => { vi.advanceTimersByTime(4000); });
    expect(calls.some((call) => call.method === "POST" && call.url.endsWith("/progress"))).toBe(false);
  });

  // §26.6, §26.18, §56: Long Strip keeps a bounded window around the reader, so a long chapter is never
  // held whole, and the window is the preload band the Master names.
  function longStub(progress: Record<string, unknown> = PROGRESS) {
    return mockApi([
      get("/api/reader/units/u2/pages", LONG),
      get("/api/reader/units/u2/progress", progress),
      get("/api/reader/settings", READER_SETTINGS),
      get("/api/works/w1", WORK),
      post("/api/reader/units/u2/progress", { ...PROGRESS, revision: 1, read_state: "partial" }),
    ]);
  }

  /** jsdom has no layout, so the stage is told how tall it is and where it is scrolled. */
  function scrollStage(stage: HTMLElement, top: number, pageHeight = 1000, count = 60) {
    Object.defineProperty(stage, "scrollHeight", { value: pageHeight * count, configurable: true });
    Object.defineProperty(stage, "clientHeight", { value: pageHeight, configurable: true });
    stage.scrollTop = top;
    fireEvent.scroll(stage);
  }

  it("holds only a bounded window of a long chapter, not the whole of it", async () => {
    longStub();
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await waitFor(() => {
      const mounted = screen.getAllByRole("img", { name: /page \d/i });
      expect(mounted.length).toBeLessThanOrEqual(12);          // previous 4 + current + next 7
      expect(mounted.length).toBeGreaterThan(1);
    });
    expect(screen.getAllByRole("img", { name: /page \d/i }).length).toBeLessThan(60);
  });

  it("moves the window as the reader scrolls, and keeps the scroll height steady", async () => {
    longStub();
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });
    const stage = screen.getByTestId("reader-stage");

    const sources = () => screen.getAllByRole("img", { name: /page \d/i })
      .map((img) => Number(img.getAttribute("src")!.split("/").pop()));
    expect(sources()).toContain(1);

    act(() => { scrollStage(stage, 20_000); });                // about page 21 of 60

    await waitFor(() => expect(sources()).toContain(21));
    expect(sources()).not.toContain(1);                        // the far page was released
    expect(sources().length).toBeLessThanOrEqual(12);

    // The spacers stand in for what is not mounted, so the strip keeps its full height.
    const total = [...stage.querySelectorAll<HTMLElement>("[data-spacer]")]
      .reduce((sum, node) => sum + Number(node.dataset.pages), 0)
      + screen.getAllByRole("img", { name: /page \d/i }).length;
    expect(total).toBe(60);
  });

  it("preloads the next seven and the previous four, and no further", async () => {
    longStub({ ...PROGRESS, read_state: "partial", fraction: 0.5, locator: { page: 30 }, revision: 2 });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await waitFor(() => {
      const shown = screen.getAllByRole("img", { name: /page \d/i })
        .map((img) => Number(img.getAttribute("src")!.split("/").pop()));
      expect(Math.min(...shown)).toBe(26);                     // 30 − 4
      expect(Math.max(...shown)).toBe(37);                     // 30 + 7
    });
  });

  it("resumes inside the window, so virtualization does not lose the position", async () => {
    longStub({ ...PROGRESS, read_state: "partial", fraction: 0.75, locator: { page: 45 }, revision: 3 });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await waitFor(() =>
      expect(screen.getByRole("toolbar", { name: /reading progress/i })).toHaveTextContent("45 / 60"));
    const shown = screen.getAllByRole("img", { name: /page \d/i })
      .map((img) => img.getAttribute("src"));
    expect(shown).toContain("/api/reader/units/u2/pages/45");
  });

  it("writes progress as the reader scrolls, with the revision it last saw", async () => {
    const calls = longStub();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    act(() => { scrollStage(screen.getByTestId("reader-stage"), 10_000); });
    act(() => { vi.advanceTimersByTime(1500); });

    const write = calls.find((call) => call.method === "POST" && call.url.endsWith("/progress"));
    expect(write).toBeDefined();
    expect((write!.body as { locator: { page: number } }).locator.page).toBeGreaterThan(1);
    expect((write!.body as { revision: number }).revision).toBe(0);
    void user;
  });

  it("prefetches the band around a single page without putting it on screen", async () => {
    longStub({ ...PROGRESS, read_state: "partial", fraction: 0.5, locator: { page: 30 }, revision: 2 });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });

    await user.click(screen.getByRole("button", { name: /reader settings/i }));
    await user.click(within(screen.getByRole("dialog", { name: /reader settings/i }))
      .getByRole("radio", { name: /single/i }));
    await user.keyboard("{Escape}");

    // One page is on screen; §26.18's band is fetched quietly around it.
    await waitFor(() => expect(screen.getAllByRole("img", { name: /page \d/i })).toHaveLength(1));
    const stage = screen.getByTestId("reader-stage");
    const prefetched = [...stage.querySelectorAll<HTMLImageElement>("[data-preload]")]
      .map((img) => Number(img.getAttribute("src")!.split("/").pop()))
      .sort((a, b) => a - b);

    expect(Math.min(...prefetched)).toBe(26);                  // 30 − 4
    expect(Math.max(...prefetched)).toBe(37);                  // 30 + 7
    expect(prefetched).not.toContain(30);                      // the page itself is already on screen
    stage.querySelectorAll("[data-preload]").forEach((node) => {
      expect(node.getAttribute("aria-hidden")).toBe("true");   // never announced, never in the way
    });
  });

  it("reads its position from the pages themselves, not from an estimated height", async () => {
    // A chapter's pages are not all the same height. If the window were driven by an average, the reader
    // would be told they are somewhere they are not — and, after resuming, the window could shift away
    // from the page they asked for. The mounted pages' own positions are the truth (§26.6).
    longStub({ ...PROGRESS, read_state: "partial", fraction: 0.5, locator: { page: 30 }, revision: 2 });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });
    const stage = screen.getByTestId("reader-stage");
    await waitFor(() =>
      expect(screen.getByRole("toolbar", { name: /reading progress/i })).toHaveTextContent("30 / 60"));

    // The stage sits at y=0; page 33 is the one crossing the top of it.
    Object.defineProperty(stage, "getBoundingClientRect", {
      value: () => ({ top: 0, bottom: 900, height: 900 }), configurable: true });
    for (const img of stage.querySelectorAll<HTMLElement>("[data-page-slot]")) {
      const slot = Number(img.dataset.pageSlot);
      const top = (slot - 32) * 900;                      // slot 32 (page 33) starts at the top
      Object.defineProperty(img, "getBoundingClientRect", {
        value: () => ({ top, bottom: top + 900, height: 900 }), configurable: true });
    }

    act(() => { fireEvent.scroll(stage); });

    await waitFor(() =>
      expect(screen.getByRole("toolbar", { name: /reading progress/i })).toHaveTextContent("33 / 60"));
  });

  it("reserves each page's space before it loads, so the strip does not shift under the reader", async () => {
    // An <img> with nothing loaded is zero pixels tall. Without reserved space, pages loading *above* the
    // viewport push the strip down and the reader silently drifts backwards — which is what happened on
    // re-entry: the library said page 30, the reader ended up on 23 (I-11).
    longStub({ ...PROGRESS, read_state: "partial", fraction: 0.25, locator: { page: 30 }, revision: 2 });
    renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
    await screen.findAllByRole("img", { name: /page \d/i });
    await waitFor(() =>
      expect(screen.getByRole("toolbar", { name: /reading progress/i })).toHaveTextContent("30 / 60"));

    for (const page of screen.getAllByRole("img", { name: /page \d/i })) {
      expect(page.style.minBlockSize || page.style.minHeight).not.toBe("");
    }
    const spacer = screen.getByTestId("reader-stage").querySelector<HTMLElement>('[data-spacer="before"]');
    expect(spacer!.style.blockSize).toBe(`${25 * 1200}px`);      // the same estimate, used consistently
  });
});
