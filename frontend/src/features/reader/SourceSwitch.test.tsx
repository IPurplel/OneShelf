/** Master §26.16, §26.3b, §26.24, INV-25: whose source this is, and what it may honestly offer. */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ReaderScreen } from "./ReaderScreen";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

const PAGES = {
  reading_unit_id: "u2",
  pages: [{ index: 1, label: "1", url: null }, { index: 2, label: "2", url: null }],
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
  tracks: [{ id: "t1", source_id: "source-a", language: "en", kind: "source", availability: "available",
             unit_count: 2 }],
  selected_track_id: "t1",
  units: [
    { id: "u2", title: "Chapter 12", number: "12", unit_type: "chapter", volume: null, order: 1,
      release_date: null, availability: "available", url: null, downloaded: true, formats: ["cbz"],
      read_state: "partial", fraction: 0.5, read_at: null, integrity: "ok", is_new: false },
  ],
  continue_unit_id: "u2",
};

const PROGRESS = { read_state: "partial", fraction: 0.5, locator: null, revision: 3 };

const CONFIDENT = {
  unit_id: "u2", track_id: "t1", source_id: "source-a", language: "en",
  alternatives: [{ track_id: "t2", source_id: "source-b", language: "en", kind: "source",
                   availability: "available", unit_id: "u9", unit_title: "Chapter 12",
                   confident: true, reason: null }],
};

const UNSURE = {
  ...CONFIDENT,
  alternatives: [{ track_id: "t2", source_id: "source-b", language: "en", kind: "source",
                   availability: "available", unit_id: null, unit_title: null,
                   confident: false, reason: "no_match" }],
};

function stub(alternatives: unknown = CONFIDENT) {
  return mockApi([
    get("/api/reader/units/u2/pages", PAGES),
    get("/api/reader/units/u2/progress", PROGRESS),
    get("/api/reader/units/u2/alternatives", alternatives),
    get("/api/works/w1", WORK),
    get("/api/reader/settings", READER_SETTINGS),
    post("/api/reader/units/u2/progress", { ...PROGRESS, revision: 4 }),
  ]);
}

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

it("says which source and language this unit is being read from", async () => {
  stub();
  renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
  await screen.findAllByRole("img", { name: /page \d/i });

  expect(await screen.findByTestId("reader-source")).toHaveTextContent(/English · source-a/);
});

it("offers another source's copy of this unit without ever claiming the same page", async () => {
  stub();
  const u = user();
  renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
  await screen.findAllByRole("img", { name: /page \d/i });

  await u.click(screen.getByRole("button", { name: /more/i }));
  await u.click(screen.getByRole("button", { name: /change source/i }));

  const panel = screen.getByRole("dialog", { name: /change source/i });
  expect(panel).toHaveTextContent(/page layouts may differ/i);
  expect(within(panel).getByRole("button", { name: /start this unit/i })).toBeInTheDocument();

  const approximate = within(panel).getByRole("button", { name: /try approximate position/i });
  expect(approximate).toBeInTheDocument();
  expect(panel).toHaveTextContent(/approximate/i);
  expect(panel).not.toHaveTextContent(/same page|exact/i);
});

it("says so plainly when the other source's copy cannot be found, and offers its track instead", async () => {
  stub(UNSURE);
  const u = user();
  renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
  await screen.findAllByRole("img", { name: /page \d/i });

  await u.click(screen.getByRole("button", { name: /more/i }));
  await u.click(screen.getByRole("button", { name: /change source/i }));

  const panel = screen.getByRole("dialog", { name: /change source/i });
  expect(panel).toHaveTextContent(/could not find this unit/i);
  expect(within(panel).queryByRole("button", { name: /try approximate position/i })).toBeNull();
  expect(within(panel).getByRole("link", { name: /open the source-b track/i }))
    .toHaveAttribute("href", "/works/w1?track=t2");
});

it("hides the bars until they are summoned, in the minimal control mode", async () => {
  stub();
  const u = user();
  renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
  await screen.findAllByRole("img", { name: /page \d/i });

  await u.click(screen.getByRole("button", { name: /reader settings/i }));
  const settings = screen.getByRole("dialog", { name: /reader settings/i });
  await u.click(within(settings).getByRole("radio", { name: /minimal/i }));
  await u.keyboard("{Escape}");

  const bar = screen.getByRole("toolbar", { name: /reading controls/i });
  expect(bar).toHaveAttribute("data-hidden", "true");

  // A drifting mouse must not bring them back — only summoning does.
  fireEvent.mouseMove(screen.getByTestId("reader-stage"));
  expect(screen.getByRole("toolbar", { name: /reading controls/i })).toHaveAttribute("data-hidden", "true");

  await u.click(screen.getByRole("button", { name: /show the controls/i }));
  expect(screen.getByRole("toolbar", { name: /reading controls/i })).toHaveAttribute("data-hidden", "false");
});

it("shows the centre-tap hint once, and never again", async () => {
  stub();
  const u = user();
  const first = renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
  await screen.findAllByRole("img", { name: /page \d/i });

  await u.click(screen.getByRole("button", { name: /reader settings/i }));
  await u.click(within(screen.getByRole("dialog", { name: /reader settings/i }))
    .getByRole("radio", { name: /minimal/i }));
  await u.keyboard("{Escape}");
  expect(screen.getByText(/tap.*centre.*to show the controls/i)).toBeInTheDocument();

  first.unmount();
  stub();
  renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
  await screen.findAllByRole("img", { name: /page \d/i });
  expect(screen.queryByText(/tap.*centre.*to show the controls/i)).toBeNull();
});

it("holds each page's place while it loads, rather than collapsing the strip", async () => {
  stub();
  renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />);
  const pages = await screen.findAllByRole("img", { name: /page \d/i });

  const frame = pages[0]!.closest("[data-page]");
  expect(frame).toHaveAttribute("data-loaded", "false");
  expect(frame).toHaveClass("reader__page--skeleton");
});

it("opens an approximate position as approximate, and says so", async () => {
  const pages = { reading_unit_id: "u2",
                  pages: Array.from({ length: 60 }, (_, i) => ({ index: i + 1, label: String(i + 1), url: null })) };
  mockApi([
    get("/api/reader/units/u2/pages", pages),
    get("/api/reader/units/u2/progress", { read_state: "unread", fraction: 0, locator: null, revision: 0 }),
    get("/api/reader/units/u2/alternatives", CONFIDENT),
    get("/api/works/w1", WORK),
    get("/api/reader/settings", READER_SETTINGS),
    post("/api/reader/units/u2/progress", { read_state: "partial", fraction: 0.5, locator: null, revision: 1 }),
  ]);
  renderWithProviders(<ReaderScreen unitId="u2" workId="w1" />, { route: "/read/u2?work=w1&approx=0.5" });
  await screen.findAllByRole("img", { name: /page \d/i });

  // Half way through this unit's own pages — its own length, never the other source's page number.
  await waitFor(() =>
    expect(screen.getByRole("toolbar", { name: /reading progress/i })).toHaveTextContent("31 / 60"));
  expect(screen.getByRole("status")).toHaveTextContent(/approximate/i);
});
