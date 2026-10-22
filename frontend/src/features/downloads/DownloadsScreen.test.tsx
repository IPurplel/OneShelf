/** Master §16, §32.11: Downloads is operational — batches and states, not an analytics dashboard. */
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DownloadsScreen } from "./DownloadsScreen";
import { renderWithProviders, renderLive } from "@/test/render";
import { del, get, mockApi, post, type Route } from "@/test/http";

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
  it("loads per-unit detail only when a batch is expanded and can collapse it", async () => {
    const calls = mockApi([get("/api/downloads", BATCHES), get("/api/downloads/b1", {
      ...BATCHES.batches[0], jobs: [{ id: "j1", reading_unit_id: "u1", unit_title: "Chapter one",
        work_id: "w1", work_title: "The Work", state: "COMPLETED", available: true,
        bytes_done: 100, bytes_total: 100 }],
    })]);
    const user = userEvent.setup();
    renderWithProviders(<DownloadsScreen />);
    const row = (await screen.findAllByRole("listitem"))[0]!;
    expect(calls.filter(call => call.url === "/api/downloads/b1")).toHaveLength(0);
    const toggle = within(row).getByRole("button", { name: /details/i });
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await within(row).findByText("Chapter one")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: /open.*chapter one/i })).toHaveAttribute("href", "/read/u1?work=w1");
    expect(calls.filter(call => call.url === "/api/downloads/b1")).toHaveLength(1);
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("shows failed and unavailable units without offering a misleading Reader link", async () => {
    mockApi([get("/api/downloads", BATCHES), get("/api/downloads/b2", {
      ...BATCHES.batches[1], jobs: [
        { id: "j2", reading_unit_id: "u2", unit_title: "Chapter two", state: "FAILED",
          error_category: "transport", last_error: "Source timed out at https://private.invalid/?token=secret", bytes_done: 0 },
        { id: "j3", reading_unit_id: "u3", unit_title: "Chapter three", state: "COMPLETED",
          available: false, bytes_done: 0 },
      ],
    })]);
    const user = userEvent.setup();
    renderWithProviders(<DownloadsScreen />);
    const row = (await screen.findAllByRole("listitem"))[1]!;
    await user.click(within(row).getByRole("button", { name: /details/i }));
    expect(await within(row).findByText("Chapter two")).toBeInTheDocument();
    expect(row).toHaveTextContent("Failed");
    expect(row).toHaveTextContent("Source could not be reached");
    expect(row).not.toHaveTextContent("token=secret");
    expect(row).toHaveTextContent("Unavailable");
    expect(within(row).queryByRole("link", { name: /open.*chapter three/i })).not.toBeInTheDocument();
  });
  it.each([["omits", {}], ["nulls", { available: null }]] as const)(
    "never offers a completed unit as openable when the API %s its availability", async (_how, availability) => {
    // An older backend cannot say whether the file is still there, so the unit is not offered; nor is it called
    // unavailable, which the payload does not say either. The Reader stays the final authority.
    mockApi([get("/api/downloads", BATCHES), get("/api/downloads/b1", {
      ...BATCHES.batches[0], jobs: [{ id: "j5", reading_unit_id: "u5", unit_title: "Chapter five", work_id: "w1",
        work_title: "The Work", state: "COMPLETED", bytes_done: 100, ...availability }],
    })]);
    const user = userEvent.setup();
    renderWithProviders(<DownloadsScreen />);
    const row = (await screen.findAllByRole("listitem"))[0]!;
    await user.click(within(row).getByRole("button", { name: /details/i }));
    const job = (await within(row).findByText("Chapter five")).closest(".batches__job") as HTMLElement;
    expect(job).toHaveTextContent("Completed");
    expect(within(job).queryByRole("link")).not.toBeInTheDocument();
    expect(job).not.toHaveTextContent("Unavailable");
  });

  it("re-reads an open batch when a Work's files are deleted, and stops offering them", async () => {
    const answers = [true, false].map((available) => ({ ...BATCHES.batches[0], jobs: [{ id: "j1",
      reading_unit_id: "u1", unit_title: "Chapter one", work_id: "w1", state: "COMPLETED", available, bytes_done: 100 }] }));
    const detail: Route = { match: (url) => url.split("?")[0] === "/api/downloads/b1",
      get payload() { return answers.length > 1 ? answers.shift() : answers[0]; } };
    const calls = mockApi([get("/api/downloads", BATCHES), detail]);
    const user = userEvent.setup();
    const { emit } = renderLive(<DownloadsScreen />);
    const row = (await screen.findAllByRole("listitem"))[0]!;
    await user.click(within(row).getByRole("button", { name: /details/i }));
    expect(await within(row).findByRole("link", { name: /open.*chapter one/i })).toBeInTheDocument();
    const lists = calls.filter((call) => call.url === "/api/downloads").length;

    act(() => { emit("shelf.changed", { work_id: "w1", action: "files_deleted", files: 1 }); });
    await waitFor(() => expect(within(row).queryByRole("link", { name: /open.*chapter one/i })).not.toBeInTheDocument());
    expect(row).toHaveTextContent("Unavailable");
    expect(calls.filter((call) => call.url === "/api/downloads").length).toBe(lists);   // the list is not re-read
  });

  it("exposes measurable per-unit progress for an active download", async () => {
    mockApi([get("/api/downloads", BATCHES), get("/api/downloads/b1", {
      ...BATCHES.batches[0], jobs: [{ id: "j4", reading_unit_id: "u4", unit_title: "Chapter four",
        state: "DOWNLOADING", bytes_done: 50, bytes_total: 100 }],
    })]);
    const user = userEvent.setup();
    renderWithProviders(<DownloadsScreen />);
    const row = (await screen.findAllByRole("listitem"))[0]!;
    await user.click(within(row).getByRole("button", { name: /details/i }));
    const job = (await within(row).findByText("Chapter four")).closest(".batches__job")!;
    expect(job).toHaveTextContent("Downloading");
    expect(within(job as HTMLElement).getByRole("progressbar", { name: /chapter four/i })).toHaveAttribute("value", "50");
    expect(within(job as HTMLElement).getByRole("progressbar")).toHaveAttribute("max", "100");
    expect(within(job as HTMLElement).queryByRole("link")).not.toBeInTheDocument();
  });
  it("reports a failed batch action while keeping the batch visible", async () => {
    mockApi([get("/api/downloads", BATCHES),
      post("/api/downloads/b1/pause", { error: { message: "Pause unavailable" } }, 503)]);
    const user = userEvent.setup();
    renderWithProviders(<DownloadsScreen />);
    const rows = await screen.findAllByRole("listitem");
    await user.click(within(rows[0]!).getByRole("button", { name: /pause/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Pause unavailable");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });
  it("names batch states in Arabic instead of exposing status tokens", async () => {
    mockApi([get("/api/downloads", BATCHES)]);
    renderWithProviders(<DownloadsScreen />, { language: "ar" });
    const rows = await screen.findAllByRole("listitem");
    expect(within(rows[1]!).getByText("اكتمل مع مشكلات")).toBeInTheDocument();
    expect(rows[1]).not.toHaveTextContent("completed with issues");
  });
  it("shows each batch with its real state and counts", async () => {
    mockApi([get("/api/downloads", BATCHES)]);
    renderWithProviders(<DownloadsScreen />);

    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText(/2 done/i)).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/3 waiting/i)).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/1 failed/i)).toBeInTheDocument();
    expect(within(rows[0]!).getByRole("progressbar")).toHaveAttribute("value", "2");
    expect(within(rows[0]!).getByRole("progressbar")).toHaveAttribute("max", "5");
    expect(within(rows[1]!).getByRole("progressbar")).toHaveAttribute("value", "6");
    expect(within(rows[1]!).getByRole("progressbar")).toHaveAttribute("max", "6");
    expect(within(rows[0]!).getByRole("button", { name: /pause.*b1/i })).toBeInTheDocument();
  });

  it.each(["en", "ar"] as const)("shows canceled units in the batch total in %s", async (language) => {
    mockApi([get("/api/downloads", { batches: [{ ...BATCHES.batches[0], completed: 1, pending: 0, canceled: 2 }] })]);
    renderWithProviders(<DownloadsScreen />, { language });
    const row = (await screen.findAllByRole("listitem"))[0]!;
    expect(row).toHaveTextContent(language === "en" ? "2 canceled" : "2 ملغى");
    expect(within(row).getByRole("progressbar")).toHaveAttribute("value", "3");
    expect(within(row).getByRole("progressbar")).toHaveAttribute("max", "3");
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
    expect(document.querySelector(".shelf__case, canvas")).toBeNull();
  });

  it("says plainly when nothing has been downloaded", async () => {
    mockApi([get("/api/downloads", { batches: [] })]);
    renderWithProviders(<DownloadsScreen />);
    expect(await screen.findByText(/nothing has been downloaded yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /my shelf/i })).toHaveAttribute("href", "/shelf");
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
