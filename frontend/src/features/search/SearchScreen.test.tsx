/** Master §6, §31, §32.7: search is local-first, streams, and is truthful about sources. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SearchScreen } from "./SearchScreen";
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
  source_status: { mangadex: "ok", tapas: "failed" },
  sources_done: 2, sources_failed: 1,
};

beforeEach(() => vi.stubGlobal("EventSource", FakeEventSource));
afterEach(() => vi.unstubAllGlobals());

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
