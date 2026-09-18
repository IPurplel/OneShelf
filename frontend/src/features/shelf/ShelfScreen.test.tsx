/** Master §22, §32.9: My Shelf is library-first, searched locally, and honest when empty. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShelfScreen } from "./ShelfScreen";
import { renderWithProviders } from "@/test/render";
import { get, mockApi } from "@/test/http";

const ENTRY = {
  work_id: "w1", title: "The Irregular Chronicle", added_at: "2026-09-18T10:00:00+00:00",
  is_favorite: false, is_pinned: false, completed_at: null, releases_since_completion: 0,
};

afterEach(() => vi.unstubAllGlobals());

describe("My Shelf", () => {
  it("shows the saved works on shelves", async () => {
    mockApi([get("/api/shelf", { view: "all", entries: [ENTRY] })]);
    renderWithProviders(<ShelfScreen />);
    const shelf = await screen.findByRole("region", { name: /my shelf/i });
    expect(within(shelf).getByRole("link", { name: /irregular chronicle/i })).toHaveAttribute("href", "/works/w1");
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
});
