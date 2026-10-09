/** Master §22, §32.9: My Shelf is library-first, searched locally, and honest when empty. */
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShelfScreen } from "./ShelfScreen";
import { renderWithProviders } from "@/test/render";
import { del, get, mockApi } from "@/test/http";

const ENTRY = {
  work_id: "w1", title: "The Irregular Chronicle", added_at: "2026-09-18T10:00:00+00:00",
  is_favorite: false, is_pinned: false, completed_at: null, releases_since_completion: 0,
};

afterEach(() => vi.unstubAllGlobals());

const COVERED = "/api/covers?source=oneshelf.tapas&url=https%3A%2F%2Fus-a.tapas.io%2Fc.jpg";

describe("Shelf covers", () => {
  it("shows each work's known cover", async () => {
    mockApi([get("/api/shelf", { view: "all", entries: [{ ...ENTRY, cover_url: COVERED }] })]);
    const { container } = renderWithProviders(<ShelfScreen />);
    await screen.findAllByText(ENTRY.title);
    expect(container.querySelector(".workcard img")).toHaveAttribute("src", COVERED);
  });
});

describe("My Shelf", () => {
  it.each(["en", "ar"] as const)("moves shelf tab focus and selection by keyboard in %s", async (language) => {
    mockApi([get("/api/shelf", { view: "all", entries: [ENTRY] })]);
    const user = userEvent.setup();
    renderWithProviders(<ShelfScreen />, { language });
    const tabs = within(await screen.findByRole("tablist")).getAllByRole("tab");
    tabs[0]!.focus();
    await user.keyboard("{ArrowRight}");
    expect(tabs[1]).toHaveFocus();
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Home}{ArrowLeft}");
    expect(tabs.at(-1)).toHaveFocus();
    expect(tabs.at(-1)).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{End}");
    expect(tabs.at(-1)).toHaveAttribute("tabindex", "0");
    expect(tabs[0]).toHaveAttribute("tabindex", "-1");
  });

  it("shows a localized Arabic service failure through the shared resource path", async () => {
    mockApi([get("/api/shelf", { error: { code: "SERVICE_UNAVAILABLE", message: "Service temporarily unavailable" } }, 503)]);
    renderWithProviders(<ShelfScreen />, { language: "ar" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/تعذّر إكمال الطلب/);
    expect(screen.getByRole("alert")).not.toHaveTextContent("Service temporarily unavailable");
  });

  it("shows the saved works on shelves", async () => {
    mockApi([get("/api/shelf", { view: "all", entries: [ENTRY] })]);
    renderWithProviders(<ShelfScreen />);
    const shelf = await screen.findByRole("region", { name: /my shelf/i });
    expect(within(shelf).getByRole("link", { name: /irregular chronicle/i })).toHaveAttribute("href", "/works/w1");
  });

  it("sorts the shelf by title or by when a work arrived, without asking the library again", async () => {
    // §32.9 asks for sort beside search and the Grid/List choice. The shelf is already local and whole,
    // so ordering it is the screen's own job — nothing needs re-fetching to change the order.
    const zebra = { ...ENTRY, work_id: "w2", title: "Zebra Tales", added_at: "2026-09-19T10:00:00+00:00" };
    const calls = mockApi([get("/api/shelf", { view: "all", entries: [zebra, ENTRY] })]);
    const user = userEvent.setup();
    renderWithProviders(<ShelfScreen />);
    const shelf = await screen.findByRole("region", { name: /my shelf/i });

    const order = () => within(shelf).getAllByRole("link").map((link) => link.getAttribute("href"));
    expect(order()).toEqual(["/works/w2", "/works/w1"]);          // as the library ordered them

    const before = calls.length;
    await user.selectOptions(screen.getByRole("combobox", { name: /sort/i }), "title");
    expect(order()).toEqual(["/works/w1", "/works/w2"]);          // The Irregular Chronicle, then Zebra
    expect(calls.length).toBe(before);

    await user.selectOptions(screen.getByRole("combobox", { name: /sort/i }), "added");
    expect(order()).toEqual(["/works/w2", "/works/w1"]);
  });

  it("offers the views the Master names and asks the library for the chosen one", async () => {
    const calls = mockApi([get("/api/shelf", { view: "all", entries: [ENTRY] })]);
    const user = userEvent.setup();
    renderWithProviders(<ShelfScreen />);
    await screen.findByRole("region", { name: /my shelf/i });

    const tabs = screen.getByRole("tablist", { name: /views/i });
    expect(within(tabs).getAllByRole("tab").map((t) => t.textContent)).toEqual(
      ["All", "Saved", "Reading", "Completed", "Favorites", "Pinned"]);

    await user.click(within(tabs).getByRole("tab", { name: "Completed" }));
    expect(calls.some((call) => call.url.includes("view=completed"))).toBe(true);
  });

  it("searches the shelf locally rather than the internet", async () => {
    const calls = mockApi([get("/api/shelf", { view: "search", entries: [ENTRY] })]);
    const user = userEvent.setup();
    renderWithProviders(<ShelfScreen />);
    await screen.findByRole("region", { name: /my shelf/i });

    await user.type(screen.getByRole("searchbox", { name: /search your shelf/i }), "irregular");
    expect(calls.some((call) => call.url.includes("q=irregular"))).toBe(true);
    expect(calls.every((call) => call.url.startsWith("/api/shelf"))).toBe(true);
  });

  it("keeps search focused and editable while slower shelf responses arrive out of order", async () => {
    const requests: { url: string; respond: (entries: typeof ENTRY[]) => void }[] = [];
    vi.stubGlobal("fetch", vi.fn((input: string) => new Promise<Response>((resolve) => {
      requests.push({
        url: input,
        respond: (entries) => resolve(new Response(JSON.stringify({ view: "search", entries }), {
          headers: { "Content-Type": "application/json" },
        })),
      });
    })));
    const user = userEvent.setup();
    renderWithProviders(<ShelfScreen />);
    await waitFor(() => expect(requests).toHaveLength(1));
    await act(async () => requests[0]!.respond([]));

    const search = screen.getByRole("searchbox", { name: /search your shelf/i });
    await user.click(search);
    await user.type(search, "abc");
    expect(search).toHaveValue("abc");
    expect(search).toHaveFocus();
    expect(search).toBeEnabled();
    expect(screen.getByRole("combobox", { name: /sort/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /list view/i })).toBeEnabled();

    await waitFor(() => expect(requests.some((request) => request.url.includes("q=abc"))).toBe(true));
    const newest = requests.find((request) => request.url.includes("q=abc"))!;
    const older = requests.find((request) => request.url.includes("q=a"))!;
    await act(async () => newest.respond([{ ...ENTRY, title: "Newest result" }]));
    await act(async () => older.respond([{ ...ENTRY, title: "Stale result" }]));
    expect(await screen.findByRole("link", { name: /newest result/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /stale result/i })).not.toBeInTheDocument();
  });

  it.each(["en", "ar"] as const)("labels whole-shelf search as All and restores the prior view in %s", async (language) => {
    mockApi([get("/api/shelf", { view: "search", entries: [ENTRY] })]);
    const user = userEvent.setup();
    renderWithProviders(<ShelfScreen />, { language });
    const all = await screen.findByRole("tab", { name: language === "en" ? "All" : "الكل" });
    const saved = document.getElementById("shelf-tab-saved")!;
    const panel = screen.getByRole("tabpanel");
    await user.click(saved);

    const search = screen.getByRole("searchbox");
    await user.type(search, "a");
    expect(all).toHaveAttribute("aria-selected", "true");
    expect(all).toHaveAttribute("tabindex", "0");
    expect(saved).toHaveAttribute("aria-selected", "false");
    expect(panel).toHaveAttribute("aria-labelledby", "shelf-tab-all");

    await user.clear(search);
    expect(saved).toHaveAttribute("aria-selected", "true");
    expect(saved).toHaveAttribute("tabindex", "0");
    expect(panel).toHaveAttribute("aria-labelledby", "shelf-tab-saved");
  });

  it.each(["en", "ar"] as const)("distinguishes no search matches from an empty shelf in %s", async (language) => {
    mockApi([get("/api/shelf", { view: "search", entries: [] })]);
    const user = userEvent.setup();
    renderWithProviders(<ShelfScreen />, { language });
    await screen.findByText(language === "en" ? "Nothing on this shelf yet." : "لا شيء على هذا الرفّ بعد.");

    await user.type(screen.getByRole("searchbox"), "missing");
    expect(await screen.findByText(language === "en" ? "No works match your search." : "لا توجد أعمال تطابق بحثك.")).toBeInTheDocument();
    expect(screen.queryByText(language === "en" ? "Nothing on this shelf yet." : "لا شيء على هذا الرفّ بعد.")).not.toBeInTheDocument();
  });

  it("says the shelf is empty without inventing anything", async () => {
    mockApi([get("/api/shelf", { view: "all", entries: [] })]);
    renderWithProviders(<ShelfScreen />);
    expect(await screen.findByText(/nothing on this shelf yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("switches between grid and list without losing the works", async () => {
    mockApi([get("/api/shelf", { view: "all", entries: [ENTRY] })]);
    const user = userEvent.setup();
    renderWithProviders(<ShelfScreen />);
    const shelf = await screen.findByRole("region", { name: /my shelf/i });

    await user.click(screen.getByRole("button", { name: /list view/i }));
    expect(within(shelf).getByRole("link", { name: /irregular chronicle/i })).toBeInTheDocument();
    expect(shelf).toHaveAttribute("data-layout", "list");
  });

  it("removes a work from a shelf row, with the same confirmation Work Details gives", async () => {
    const summary = { work_id: "w1", files: 3, bytes: 9_000_000, has_progress: true, is_followed: false };
    const calls = mockApi([get("/api/shelf", { view: "all", entries: [ENTRY] }),
                           get("/api/shelf/w1/removal-summary", summary),
                           del("/api/shelf/w1", summary)]);
    const user = userEvent.setup();
    renderWithProviders(<ShelfScreen />);
    await screen.findByRole("region", { name: /my shelf/i });

    // Row actions live in the list layout: the grid is the shelf motif, and a chip on every cover would
    // collapse the plank the covers stand on (§32.9).
    await user.click(screen.getByRole("button", { name: /list view/i }));
    await user.click(screen.getByRole("button", { name: /manage/i }));
    await user.click(screen.getByRole("button", { name: /remove from shelf/i }));

    const dialog = await screen.findByRole("dialog", { name: /remove from shelf/i });
    expect(dialog).toHaveTextContent(/3 downloaded files/i);
    expect(dialog).toHaveTextContent(/reading progress/i);
    await user.click(within(dialog).getByRole("button", { name: /keep the files/i }));

    expect(calls.find((call) => call.method === "DELETE")?.url).toBe("/api/shelf/w1?delete_files=false");
  });
});
