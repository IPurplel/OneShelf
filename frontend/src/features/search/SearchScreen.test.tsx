/** Master §6, §31, §32.7: search is local-first, streams, and is truthful about sources. */
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SearchScreen } from "./SearchScreen";
import { ApiError, api } from "@/api/client";
import { renderWithProviders } from "@/test/render";

type Handler = (event: { data: string }) => void;

class FakeEventSource {
  static last: FakeEventSource | null = null;
  listeners = new Map<string, Handler[]>();
  closed = false;

  constructor(readonly url: string) { FakeEventSource.last = this; }

  addEventListener(name: string, handler: Handler) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), handler]);
  }

  close() { this.closed = true; }

  emit(stage: string, payload: unknown) {
    for (const handler of this.listeners.get(stage) ?? []) handler({ data: JSON.stringify(payload) });
  }
}

const LOCAL = {
  stage: "local",
  results: [{ work_id: "w1", title: "The Irregular Chronicle", content_type: "manga", soft: false,
              availability: { en: 1 }, provenance: [{ source_id: "local", listing_key: "k", language: "en",
                                                      title: "The Irregular Chronicle", url: null }] }],
  source_status: {}, sources_total: 2, sources_done: 0, sources_failed: 0,
};

const COMPLETE = {
  ...LOCAL,
  stage: "complete",
  source_status: { mangadex: { state: "done" }, tapas: { state: "failed", category: "transport" } },
  sources_done: 1, sources_failed: 1,
};

beforeEach(() => vi.stubGlobal("EventSource", FakeEventSource));
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Search", () => {
  it("shows what the library already knows before any source answers", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SearchScreen />);
    await user.type(screen.getByRole("searchbox", { name: /search/i }), "irregular{Enter}");

    FakeEventSource.last!.emit("local", LOCAL);
    expect(await screen.findByText("The Irregular Chronicle")).toBeInTheDocument();
    expect(FakeEventSource.last!.url).toContain("q=irregular");
  });

  it("says which sources are still working and which failed, without hiding results", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SearchScreen />);
    await user.type(screen.getByRole("searchbox", { name: /search/i }), "irregular{Enter}");

    FakeEventSource.last!.emit("local", LOCAL);
    await screen.findByText("The Irregular Chronicle");
    expect(screen.getByRole("status")).toHaveTextContent(/0 of 2/i);

    FakeEventSource.last!.emit("complete", COMPLETE);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/1 source could not answer/i));
    expect(screen.getByRole("button", { name: /try tapas again/i })).toBeInTheDocument();
    expect(screen.getByText("The Irregular Chronicle")).toBeInTheDocument();
  });

  it("closes the stream when the search changes", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SearchScreen />);
    const box = screen.getByRole("searchbox", { name: /search/i });
    await user.type(box, "one{Enter}");
    const first = FakeEventSource.last!;
    await user.clear(box);
    await user.type(box, "two{Enter}");
    expect(first.closed).toBe(true);
  });

  it("offers the plain empty state before anything is typed", () => {
    renderWithProviders(<SearchScreen />);
    expect(screen.getByText(/search your library and your sources/i)).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows a result's languages and source count rather than a fake score", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SearchScreen />);
    await user.type(screen.getByRole("searchbox", { name: /search/i }), "irregular{Enter}");
    FakeEventSource.last!.emit("local", LOCAL);

    const card = (await screen.findByText("The Irregular Chronicle")).closest(".workcard");
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText(/1 source/i)).toBeInTheDocument();
    expect(screen.queryByText(/%|score|rank/i)).not.toBeInTheDocument();
  });
});

async function startSearch(stage = "complete") {
  const user = userEvent.setup();
  renderWithProviders(<SearchScreen />);
  const box = screen.getByRole("searchbox");
  await user.type(box, "one{Enter}");
  act(() => FakeEventSource.last!.emit(stage, COMPLETE));
  return { user, box };
}

describe("Search regressions", () => {
  it("offers Retry only for failed API status objects", async () => {
    await startSearch("partial");
    act(() => FakeEventSource.last!.emit("partial", { ...COMPLETE, source_status: {
      working: { state: "pending" }, cached: { state: "cached" }, done: { state: "done", complete: true },
      failed: { state: "failed", category: "transport" },
    } }));
    expect(screen.getAllByRole("button").map(button => button.textContent)).toEqual(["Try failed again"]);
  });

  it("clears results and status on empty submission, and ignores late stream events", async () => {
    const { user, box } = await startSearch();
    const old = FakeEventSource.last!;
    await user.clear(box);
    await user.type(box, " {Enter}");
    expect(old.closed).toBe(true);
    act(() => old.emit("complete", COMPLETE));
    expect(screen.queryByText("The Irregular Chronicle")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try/i })).not.toBeInTheDocument();
  });

  it.each([false, true])("ignores a stale retry after changing away and back (rejection=%s)", async reject => {
    let resolve!: (value: typeof COMPLETE) => void;
    let fail!: (reason: Error) => void;
    vi.spyOn(api, "post").mockImplementation(() => new Promise((yes, no) => { resolve = yes; fail = no; }));
    const { user, box } = await startSearch();
    await user.click(screen.getByRole("button", { name: /try tapas/i }));
    await user.clear(box);
    await user.type(box, "two{Enter}");
    await user.clear(box);
    await user.type(box, "one{Enter}");
    await act(async () => { if (reject) fail(new Error("Old failure")); else resolve(COMPLETE); });
    expect(screen.queryByText("The Irregular Chronicle")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reports retry errors while keeping useful results and permits another retry", async () => {
    vi.spyOn(api, "post").mockRejectedValueOnce(new ApiError(503, "OFFLINE", "Source unavailable"))
      .mockResolvedValueOnce({ ...COMPLETE, source_status: { tapas: { state: "done" } }, sources_failed: 0 });
    const { user } = await startSearch();
    await user.click(screen.getByRole("button", { name: /try tapas/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Source unavailable/);
    expect(screen.getByText("The Irregular Chronicle")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /try tapas/i }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /try tapas/i })).not.toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
