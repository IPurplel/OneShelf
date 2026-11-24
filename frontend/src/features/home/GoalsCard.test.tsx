/** Reading goals on Home (asked for 2026-11-10): a yearly book goal, and a daily streak that encourages. */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GoalsCard } from "./GoalsCard";
import { renderWithProviders } from "@/test/render";
import { get, mockApi } from "@/test/http";

const summary = (over: { books?: object; streak?: object } = {}) => ({
  books: { year: 2026, goal: 20, finished: 9, expected_by_now: 8, ahead: 1, recent: [], ...over.books },
  streak: { current: 5, longest: 12, read_today: false, last_7: [false, false, true, true, true, true, false],
            ...over.streak },
});

afterEach(() => vi.unstubAllGlobals());

describe("Reading goals", () => {
  it("shows the year's books against the goal and whether you are on pace", async () => {
    const calls = mockApi([get("/api/goals", summary())]);
    renderWithProviders(<GoalsCard />);
    expect(await screen.findByText(/9 of 20 books in 2026/i)).toBeInTheDocument();
    expect(screen.getByText(/1 book ahead/i)).toBeInTheDocument();
    expect(calls[0]!.url).toMatch(/offset=-?\d+/);           // the reader's own day, not the server's
  });

  it("turns a big gap into a plan for the rest of the year instead of a scolding", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 10, 12));               // 10 November: 52 days left in the year
    mockApi([get("/api/goals", summary({ books: { goal: 12, finished: 0, expected_by_now: 10, ahead: -10 } }))]);
    renderWithProviders(<GoalsCard />);
    expect(await screen.findByText(/12 books left this year: one every 4 days gets you there/i)).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("keeps the streak alive with a nudge before today's reading", async () => {
    mockApi([get("/api/goals", summary())]);
    renderWithProviders(<GoalsCard />);
    expect(await screen.findByText(/5 days in a row/i)).toBeInTheDocument();
    expect(screen.getByText(/read a page today to make it 6/i)).toBeInTheDocument();
  });

  it("says so when today's reading is done", async () => {
    mockApi([get("/api/goals", summary({ streak: { read_today: true, current: 6 } }))]);
    renderWithProviders(<GoalsCard />);
    expect(await screen.findByText(/you read today/i)).toBeInTheDocument();
  });

  it("asks for a goal when none is set, and saves it", async () => {
    const calls = mockApi([get("/api/goals", summary({ books: { goal: null, expected_by_now: null, ahead: null } })),
      { match: (url: string, init?: RequestInit) => url.startsWith("/api/goals") && init?.method === "PUT",
        payload: summary() }]);
    const user = userEvent.setup();
    renderWithProviders(<GoalsCard />);
    await user.click(await screen.findByRole("button", { name: /set a goal/i }));
    const field = screen.getByRole("spinbutton", { name: /books this year/i });
    await user.clear(field);
    await user.type(field, "24{Enter}");
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ books_per_year: 24 });
  });
});
