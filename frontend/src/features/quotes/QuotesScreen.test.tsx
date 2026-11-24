/** Quotes (asked for 2026-11-10): every highlight from every book on one page, to reread, copy and share. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { QuotesScreen } from "./QuotesScreen";
import { renderWithProviders } from "@/test/render";
import { del, get, mockApi } from "@/test/http";

const QUOTES = { highlights: [
  { id: "h2", text: "Later words.", colour: "yellow", created_at: "2026-11-10T09:00:00+00:00", unit_id: "u2",
    unit_title: "Chapter 2", work_id: "w1", work_title: "The Stranger", cover_url: null },
  { id: "h1", text: "كان الصمت أوله.", colour: "green", created_at: "2026-11-09T09:00:00+00:00", unit_id: "u9",
    unit_title: "الفصل الأول", work_id: "w2", work_title: "الأمير", cover_url: null },
] };

afterEach(() => vi.unstubAllGlobals());

describe("Quotes", () => {
  it("shows every highlight with the book and chapter it came from, linked back to the page", async () => {
    mockApi([get("/api/highlights", QUOTES)]);
    renderWithProviders(<QuotesScreen />);
    const quotes = await screen.findAllByRole("article");
    expect(quotes).toHaveLength(2);
    expect(within(quotes[0]!).getByText("Later words.")).toBeInTheDocument();
    expect(within(quotes[0]!).getByRole("link", { name: /the stranger/i }))
      .toHaveAttribute("href", "/read/u2?work=w1");
  });

  it("names the chapter only when it says something the book's title does not", async () => {
    // A book that is one file has one "chapter" named like itself: the source line said the title twice.
    mockApi([get("/api/highlights", { highlights: [{ ...QUOTES.highlights[0]!, unit_title: "The Stranger" }] })]);
    renderWithProviders(<QuotesScreen />);
    const quote = (await screen.findAllByRole("article"))[0]!;
    expect(within(quote).getAllByText("The Stranger")).toHaveLength(1);
  });

  it("narrows to one book", async () => {
    mockApi([get("/api/highlights", QUOTES)]);
    const user = userEvent.setup();
    renderWithProviders(<QuotesScreen />);
    await user.click(await screen.findByRole("button", { name: /الأمير/ }));
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByText("كان الصمت أوله.")).toBeInTheDocument();
  });

  it("copies a quote with where it came from", async () => {
    mockApi([get("/api/highlights", QUOTES)]);
    const user = userEvent.setup();                 // installs its own clipboard; ours goes in after it
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderWithProviders(<QuotesScreen />);
    const first = (await screen.findAllByRole("article"))[0]!;
    await user.click(within(first).getByRole("button", { name: /copy/i }));
    expect(writeText).toHaveBeenCalledWith("“Later words.”\n— The Stranger");
  });

  it("deletes a quote", async () => {
    const calls = mockApi([get("/api/highlights", QUOTES), del("/api/reader/highlights/h2", { removed: true })]);
    const user = userEvent.setup();
    renderWithProviders(<QuotesScreen />);
    const first = (await screen.findAllByRole("article"))[0]!;
    await user.click(within(first).getByRole("button", { name: /delete/i }));
    expect(calls.some((c) => c.url === "/api/reader/highlights/h2" && c.method === "DELETE")).toBe(true);
  });

  it("says where quotes come from when there are none yet", async () => {
    mockApi([get("/api/highlights", { highlights: [] })]);
    renderWithProviders(<QuotesScreen />);
    expect(await screen.findByText(/highlight a sentence while reading/i)).toBeInTheDocument();
  });
});
