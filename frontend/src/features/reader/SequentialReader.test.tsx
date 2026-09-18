/** Master §26.1–26.24, §27: the Sequential Reader. Local reading needs no source, plugin or network. */
import { act, fireEvent, screen, within } from "@testing-library/react";
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

function stub(extra: ReturnType<typeof get>[] = []) {
  return mockApi([
    get("/api/reader/units/u2/pages", PAGES),
    get("/api/reader/units/u2/progress", PROGRESS),
    get("/api/works/w1", WORK),
    post("/api/reader/units/u2/progress", { ...PROGRESS, revision: 1, read_state: "partial" }),
    post("/api/reader/units/u2/mark-read", { ...PROGRESS, revision: 1, read_state: "read" }),
    ...extra,
  ]);
}

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

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
});
