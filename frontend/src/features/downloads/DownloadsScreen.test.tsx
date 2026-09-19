/** Master §16, §32.11: Downloads is operational — batches and states, not an analytics dashboard. */
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DownloadsScreen } from "./DownloadsScreen";
import { renderWithProviders, renderLive } from "@/test/render";
import { del, get, mockApi, post } from "@/test/http";

const BATCHES = {
  batches: [
    { batch_id: "b1", state: "active", completed: 2, failed: 0, pending: 3, canceled: 0, skipped: 0,
      counts: { COMPLETED: 2, QUEUED: 3 } },
    { batch_id: "b2", state: "completed_with_issues", completed: 4, failed: 1, pending: 0, canceled: 0, skipped: 1,
      counts: { COMPLETED: 4, FAILED: 1 } },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe("Downloads", () => {
  it("shows each batch with its real state and counts", async () => {
    mockApi([get("/api/downloads", BATCHES)]);
    renderWithProviders(<DownloadsScreen />);

    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText(/2 done/i)).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/3 waiting/i)).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/1 failed/i)).toBeInTheDocument();
  });

  it("offers pause, resume, retry and cancel where they make sense", async () => {
    const calls = mockApi([
      get("/api/downloads", BATCHES),
      post("/api/downloads/b1/pause", { batch_id: "b1", state: "paused" }),
      post("/api/downloads/b2/retry-failed", { batch_id: "b2", state: "active" }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<DownloadsScreen />);
    const rows = await screen.findAllByRole("listitem");

    await user.click(within(rows[0]!).getByRole("button", { name: /pause/i }));
    await user.click(within(rows[1]!).getByRole("button", { name: /retry failed/i }));
    expect(calls.some((call) => call.url === "/api/downloads/b1/pause")).toBe(true);
    expect(calls.some((call) => call.url === "/api/downloads/b2/retry-failed")).toBe(true);
  });

  it("explains that clearing history keeps the files and the progress", async () => {
    const calls = mockApi([get("/api/downloads", BATCHES), del("/api/downloads/history", { removed: 2 })]);
    const user = userEvent.setup();
    renderWithProviders(<DownloadsScreen />);
    await screen.findAllByRole("listitem");

    await user.click(screen.getByRole("button", { name: /clear history/i }));
    const dialog = await screen.findByRole("dialog", { name: /clear history/i });
    expect(dialog).toHaveTextContent(/downloaded files.*stay|keeps? your downloaded files/i);
    expect(dialog).toHaveTextContent(/progress/i);

    await user.click(within(dialog).getByRole("button", { name: /^clear history$/i }));
    expect(calls.some((call) => call.method === "DELETE" && call.url.startsWith("/api/downloads/history"))).toBe(true);
  });

  it("uses no shelves and no charts", async () => {
    mockApi([get("/api/downloads", BATCHES)]);
    renderWithProviders(<DownloadsScreen />);
    await screen.findAllByRole("listitem");
    expect(document.querySelector(".shelf__plank, canvas")).toBeNull();
  });

  it("says plainly when nothing has been downloaded", async () => {
    mockApi([get("/api/downloads", { batches: [] })]);
    renderWithProviders(<DownloadsScreen />);
    expect(await screen.findByText(/nothing has been downloaded yet/i)).toBeInTheDocument();
  });

  it("follows the library live, re-reading only what changed", async () => {
    // §36: an event says something happened; the screen re-reads rather than trusting the payload.
    const calls = mockApi([get("/api/downloads", BATCHES)]);
    const { emit } = renderLive(<DownloadsScreen />);
    await screen.findAllByRole("listitem");
    const reads = () => calls.filter((call) => call.url === "/api/downloads" && call.method === "GET").length;
    const before = reads();

    act(() => { emit("download.batch", { batch_id: "b1", queued: 3 }); });
    await waitFor(() => expect(reads()).toBe(before + 1));

    act(() => { emit("shelf.changed", { work_id: "w1" }); });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(reads()).toBe(before + 1);      // someone else's event is not this screen's business
  });
});
