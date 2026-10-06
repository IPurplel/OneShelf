/** Master §20, §32.10: Following is a reading journal — new releases first, no charts. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FollowingScreen } from "./FollowingScreen";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

const FOLLOWS = {
  follows: [
    { work_id: "w1", work_title: "The Irregular Chronicle", track_id: "t1", source_id: "mangadex", language: "en", state: "new_releases",
      last_attempted_at: "2026-09-18T09:00:00+00:00", last_successful_at: "2026-09-18T09:00:00+00:00",
      unseen_releases: 3 },
    { work_id: "w2", work_title: "Second Story", track_id: "t2", source_id: "tapas", language: "en", state: "degraded",
      last_attempted_at: "2026-09-18T08:00:00+00:00", last_successful_at: "2026-09-10T08:00:00+00:00",
      unseen_releases: 0 },
    { work_id: "w3", work_title: "Third Story", track_id: "t3", source_id: "local", language: "ar", state: "up_to_date",
      last_attempted_at: "2026-09-18T07:00:00+00:00", last_successful_at: "2026-09-18T07:00:00+00:00",
      unseen_releases: 0 },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe("Following", () => {
  it("reports a failed check without removing the followed rows", async () => {
    mockApi([get("/api/follows", FOLLOWS),
      post("/api/follows/check-all", { error: { message: "Check unavailable" } }, 503)]);
    const user = userEvent.setup();
    renderWithProviders(<FollowingScreen />);
    await screen.findByRole("region", { name: "New releases" });
    await user.click(screen.getByRole("button", { name: /check all/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Check unavailable");
    expect(screen.getByRole("link", { name: "The Irregular Chronicle" })).toBeInTheDocument();
  });
  it("keeps two languages of one Work distinct and checks the chosen language", async () => {
    const rows = [
      { ...FOLLOWS.follows[0], unseen_releases: 0, state: "up_to_date", track_id: "t-en" },
      { ...FOLLOWS.follows[0], unseen_releases: 0, state: "up_to_date", language: "ar", track_id: "t-ar" },
    ];
    const calls = mockApi([get("/api/follows", { follows: rows }),
      post("/api/follows/w1/check", { state: "up_to_date", new_units: [] })]);
    const user = userEvent.setup();
    renderWithProviders(<FollowingScreen />);
    const section = await screen.findByRole("region", { name: "Up to date" });
    const links = within(section).getAllByRole("link", { name: "The Irregular Chronicle" });
    expect(links.map(link => link.getAttribute("href"))).toEqual([
      "/works/w1?track=t-en", "/works/w1?track=t-ar",
    ]);
    await user.click(within(section).getAllByRole("button", { name: /check now/i })[1]!);
    expect(calls).toContainEqual({ url: "/api/follows/w1/check?language=ar", method: "POST", body: undefined });
  });
  it("puts new releases first, then what needs attention, then what is up to date", async () => {
    mockApi([get("/api/follows", FOLLOWS)]);
    renderWithProviders(<FollowingScreen />);

    const sections = await screen.findAllByRole("region");
    expect(sections.map((section) => section.getAttribute("aria-label"))).toEqual(
      ["New releases", "Needs attention", "Up to date"]);
  });

  it("says how many releases are waiting and when the source last answered", async () => {
    mockApi([get("/api/follows", FOLLOWS)]);
    renderWithProviders(<FollowingScreen />);

    const fresh = await screen.findByRole("region", { name: "New releases" });
    expect(within(fresh).getByText(/3 new/i)).toBeInTheDocument();
    const attention = screen.getByRole("region", { name: "Needs attention" });
    expect(within(attention).getByText(/last answered/i)).toBeInTheDocument();
  });

  it("checks one work or all of them, and never downloads by doing so", async () => {
    const calls = mockApi([
      get("/api/follows", FOLLOWS),
      post("/api/follows/w1/check", { work_id: "w1", state: "up_to_date", new_units: [] }),
      post("/api/follows/check-all", { checked: 3 }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<FollowingScreen />);
    await screen.findByRole("region", { name: "New releases" });

    await user.click(screen.getAllByRole("button", { name: /check now/i })[0]!);
    await user.click(screen.getByRole("button", { name: /check all/i }));

    expect(calls.some((call) => call.url === "/api/follows/w1/check?language=en")).toBe(true);
    expect(calls.some((call) => call.url === "/api/follows/check-all")).toBe(true);
    expect(calls.every((call) => !call.url.startsWith("/api/downloads"))).toBe(true);   // INV-09
  });

  it("has no charts or statistics", async () => {
    mockApi([get("/api/follows", FOLLOWS)]);
    renderWithProviders(<FollowingScreen />);
    await screen.findByRole("region", { name: "New releases" });
    expect(document.querySelector("canvas, svg[data-chart]")).toBeNull();
  });

  it("says plainly when nothing is followed", async () => {
    mockApi([get("/api/follows", { follows: [] })]);
    renderWithProviders(<FollowingScreen />);
    expect(await screen.findByText(/not following anything yet/i)).toBeInTheDocument();
  });
});
