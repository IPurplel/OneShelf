/** Master §32.8, §4, §22, §47: Work Details shows one Work, its tracks, and an index of units. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkScreen } from "./WorkScreen";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

const DETAILS = {
  work: {
    id: "w1", title: "The Irregular Chronicle", original_title: null, creator: "A. Writer",
    description: "A quiet story.", content_type: "manga", content_type_source: "source", aliases: [],
  },
  shelf: { on_shelf: true, favorite: false, pinned: false, completed: false },
  follow: { following: false, preferred_source_id: null, track_id: null, language: null, last_successful_at: null },
  tracks: [
    { id: "t-en", source_id: "local", language: "en", kind: "local", availability: "available", unit_count: 2 },
    { id: "t-ar", source_id: "mangadex", language: "ar", kind: "source", availability: "available", unit_count: 5 },
  ],
  selected_track_id: "t-en",
  units: [
    { id: "u1", title: "Prologue", number: null, unit_type: "prologue", volume: null, order: 1,
      release_date: null, availability: "available", url: null, downloaded: true, formats: ["cbz"],
      read_state: "read", fraction: 1, read_at: "2026-09-18T10:00:00+00:00" },
    { id: "u2", title: "Chapter 3.5", number: "3.5", unit_type: "special", volume: null, order: 2,
      release_date: "2026-09-01", availability: "available", url: null, downloaded: false, formats: [],
      read_state: "partial", fraction: 0.5, read_at: "2026-09-18T11:00:00+00:00" },
  ],
  continue_unit_id: "u2",
};

afterEach(() => vi.unstubAllGlobals());

describe("Work Details", () => {
  it("presents the work with its primary actions", async () => {
    mockApi([get("/api/works/w1", DETAILS)]);
    renderWithProviders(<WorkScreen workId="w1" />);

    expect(await screen.findByRole("heading", { level: 1, name: "The Irregular Chronicle" })).toBeInTheDocument();
    expect(screen.getByText("A. Writer")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /continue/i })).toHaveAttribute("href", "/read/u2");
    for (const action of [/follow/i, /favorite/i, /pin/i]) {
      expect(screen.getByRole("button", { name: action })).toBeInTheDocument();
    }
  });

  it("lists reading units as an index in source order, never renumbering them", async () => {
    mockApi([get("/api/works/w1", DETAILS)]);
    renderWithProviders(<WorkScreen workId="w1" />);

    const list = await screen.findByRole("list", { name: /reading units/i });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Prologue");
    expect(items[1]).toHaveTextContent("Chapter 3.5");
    expect(items[1]).toHaveTextContent("3.5");
  });

  it("shows which units are on this device and which are not", async () => {
    mockApi([get("/api/works/w1", DETAILS)]);
    renderWithProviders(<WorkScreen workId="w1" />);
    const list = await screen.findByRole("list", { name: /reading units/i });
    const items = within(list).getAllByRole("listitem");
    expect(within(items[0]!).getByText(/downloaded/i)).toBeInTheDocument();
    expect(within(items[1]!).getByRole("button", { name: /download/i })).toBeInTheDocument();
  });

  it("changes the source or language only when asked, and says what it changed to", async () => {
    const calls = mockApi([get("/api/works/w1", DETAILS)]);
    const user = userEvent.setup();
    renderWithProviders(<WorkScreen workId="w1" />);
    await screen.findByRole("heading", { level: 1 });

    const sources = screen.getByRole("tab", { name: /sources/i });
    await user.click(sources);
    const arabic = await screen.findByRole("button", { name: /mangadex.*arabic|arabic.*mangadex/i });
    await user.click(arabic);
    expect(calls.some((call) => call.url.includes("track_id=t-ar"))).toBe(true);
  });

  it("adds to the shelf through the library, not by guessing", async () => {
    const calls = mockApi([
      get("/api/works/w1", { ...DETAILS, shelf: { ...DETAILS.shelf, on_shelf: false } }),
      post("/api/shelf/w1", { work_id: "w1" }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<WorkScreen workId="w1" />);
    await screen.findByRole("heading", { level: 1 });

    await user.click(screen.getByRole("button", { name: /add to shelf/i }));
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/shelf/w1")).toBe(true);
  });

  it("explains rather than blanks out when the work is unknown", async () => {
    mockApi([get("/api/works/w1", { error: { code: "WORK_NOT_FOUND", message: "This work is not in your library." } }, 404)]);
    renderWithProviders(<WorkScreen workId="w1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not in your library/i);
  });
});
