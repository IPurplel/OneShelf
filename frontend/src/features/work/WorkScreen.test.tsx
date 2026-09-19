/** Master §32.8, §4, §22, §47: Work Details shows one Work, its tracks, and an index of units. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkScreen } from "./WorkScreen";
import { renderWithProviders } from "@/test/render";
import { del, get, mockApi, post } from "@/test/http";

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

  // §22, §47, §23/INV-10: removing from the Shelf is a decision the reader makes with the facts in front
  // of them, and it never touches Follow or progress unless they asked for that separately.
  const SUMMARY = { work_id: "w1", files: 12, bytes: 48_000_000, has_progress: true, is_followed: true };

  it("asks before removing a work that has files or progress, and says what stays", async () => {
    const calls = mockApi([get("/api/works/w1", DETAILS), get("/api/shelf/w1/removal-summary", SUMMARY)]);
    const user = userEvent.setup();
    renderWithProviders(<WorkScreen workId="w1" />);
    await screen.findByRole("heading", { level: 1, name: "The Irregular Chronicle" });

    await user.click(screen.getByRole("button", { name: /remove from shelf/i }));
    const dialog = await screen.findByRole("dialog", { name: /remove from shelf/i });

    expect(dialog).toHaveTextContent(/12 downloaded files/i);
    expect(dialog).toHaveTextContent(/reading progress/i);
    expect(dialog).toHaveTextContent(/still following/i);
    expect(within(dialog).getByRole("button", { name: /keep the files/i })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /delete the files/i })).toBeInTheDocument();
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
  });

  it("keeps the files when that is the choice", async () => {
    const calls = mockApi([get("/api/works/w1", DETAILS), get("/api/shelf/w1/removal-summary", SUMMARY),
                           del("/api/shelf/w1", { ...SUMMARY })]);
    const user = userEvent.setup();
    renderWithProviders(<WorkScreen workId="w1" />);
    await screen.findByRole("heading", { level: 1, name: "The Irregular Chronicle" });

    await user.click(screen.getByRole("button", { name: /remove from shelf/i }));
    const dialog = await screen.findByRole("dialog", { name: /remove from shelf/i });
    await user.click(within(dialog).getByRole("button", { name: /keep the files/i }));

    const removal = calls.find((call) => call.method === "DELETE");
    expect(removal?.url).toBe("/api/shelf/w1?delete_files=false");
  });

  it("deletes the files only when that is the explicit choice", async () => {
    const calls = mockApi([get("/api/works/w1", DETAILS), get("/api/shelf/w1/removal-summary", SUMMARY),
                           del("/api/shelf/w1", { ...SUMMARY, deleted_files: 12 })]);
    const user = userEvent.setup();
    renderWithProviders(<WorkScreen workId="w1" />);
    await screen.findByRole("heading", { level: 1, name: "The Irregular Chronicle" });

    await user.click(screen.getByRole("button", { name: /remove from shelf/i }));
    const dialog = await screen.findByRole("dialog", { name: /remove from shelf/i });
    await user.click(within(dialog).getByRole("button", { name: /delete the files/i }));

    const removal = calls.find((call) => call.method === "DELETE");
    expect(removal?.url).toBe("/api/shelf/w1?delete_files=true");
  });

  it("removes at once when there is nothing to lose", async () => {
    const calls = mockApi([
      get("/api/works/w1", DETAILS),
      get("/api/shelf/w1/removal-summary",
          { work_id: "w1", files: 0, bytes: 0, has_progress: false, is_followed: false }),
      del("/api/shelf/w1", { work_id: "w1", files: 0, bytes: 0, has_progress: false, is_followed: false }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<WorkScreen workId="w1" />);
    await screen.findByRole("heading", { level: 1, name: "The Irregular Chronicle" });

    await user.click(screen.getByRole("button", { name: /remove from shelf/i }));
    expect(screen.queryByRole("dialog", { name: /remove from shelf/i })).not.toBeInTheDocument();
    expect(calls.some((call) => call.method === "DELETE" && call.url.startsWith("/api/shelf/w1"))).toBe(true);
  });

  it("changes nothing when the removal is cancelled", async () => {
    const calls = mockApi([get("/api/works/w1", DETAILS), get("/api/shelf/w1/removal-summary", SUMMARY)]);
    const user = userEvent.setup();
    renderWithProviders(<WorkScreen workId="w1" />);
    await screen.findByRole("heading", { level: 1, name: "The Irregular Chronicle" });

    await user.click(screen.getByRole("button", { name: /remove from shelf/i }));
    const dialog = await screen.findByRole("dialog", { name: /remove from shelf/i });
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));

    expect(screen.queryByRole("dialog", { name: /remove from shelf/i })).not.toBeInTheDocument();
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
    expect(screen.getByRole("button", { name: /remove from shelf/i })).toBeInTheDocument();
  });

  it("marks a work completed, and offers — never performs — deleting its files", async () => {
    const calls = mockApi([get("/api/works/w1", DETAILS),
                           get("/api/shelf/w1/removal-summary", SUMMARY),
                           post("/api/shelf/w1", { work_id: "w1", favorite: false, pinned: false,
                                                   completed: true }),
                           del("/api/works/w1/files", { work_id: "w1", deleted_files: 12 })]);
    const user = userEvent.setup();
    renderWithProviders(<WorkScreen workId="w1" />);
    await screen.findByRole("heading", { level: 1, name: "The Irregular Chronicle" });

    await user.click(screen.getByRole("button", { name: /mark completed/i }));
    expect(calls.find((call) => call.method === "POST" && call.url === "/api/shelf/w1")?.body)
      .toEqual({ completed: true });

    const offer = await screen.findByRole("dialog", { name: /completed/i });
    expect(offer).toHaveTextContent(/progress/i);
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);

    await user.click(within(offer).getByRole("button", { name: /keep the files/i }));
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
  });

  it("says the same things in Arabic, where the interface mirrors", async () => {
    mockApi([get("/api/works/w1", DETAILS), get("/api/shelf/w1/removal-summary", SUMMARY)]);
    const user = userEvent.setup();
    renderWithProviders(<WorkScreen workId="w1" />, { language: "ar" });
    await screen.findByRole("heading", { level: 1, name: "The Irregular Chronicle" });

    await user.click(screen.getByRole("button", { name: "أزِل من الرف" }));
    const dialog = await screen.findByRole("dialog", { name: "أزِل من الرف" });

    expect(dialog).toHaveTextContent("ما يُزال");                  // what is removed
    expect(dialog).toHaveTextContent("ما يبقى");                   // what stays
    expect(dialog).toHaveTextContent("يبقى تقدّم قراءتك.");         // your progress stays
    expect(within(dialog).getByRole("button", { name: "أبقِ الملفات" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "احذف الملفات" })).toBeInTheDocument();
  });
});
