/** Master §20, §32.10: Following is a reading journal — new releases first, no charts. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FollowingScreen } from "./FollowingScreen";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

const FOLLOWS = {
  follows: [
    { work_id: "w1", track_id: "t1", source_id: "mangadex", language: "en", state: "new_releases",
      last_attempted_at: "2026-09-18T09:00:00+00:00", last_successful_at: "2026-09-18T09:00:00+00:00",
      unseen_releases: 3 },
    { work_id: "w2", track_id: "t2", source_id: "tapas", language: "en", state: "degraded",
      last_attempted_at: "2026-09-18T08:00:00+00:00", last_successful_at: "2026-09-10T08:00:00+00:00",
      unseen_releases: 0 },
    { work_id: "w3", track_id: "t3", source_id: "local", language: "ar", state: "up_to_date",
      last_attempted_at: "2026-09-18T07:00:00+00:00", last_successful_at: "2026-09-18T07:00:00+00:00",
      unseen_releases: 0 },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe("Following", () => {
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

    expect(calls.some((call) => call.url === "/api/follows/w1/check")).toBe(true);
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
