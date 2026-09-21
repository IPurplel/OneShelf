/**
 * Opening a search result (found on the real UI, 2026-09-21): a live result that has no Work yet used to
 * render as a plain span — seen, never opened. Now every result is a link or a button. Opening binds exactly
 * the listing the person chose; when a result was grouped from several sources, they choose which.
 */
import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderApp } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

type Handler = (event: { data: string }) => void;

class FakeEventSource {
  static last: FakeEventSource | null = null;
  listeners = new Map<string, Handler[]>();
  constructor(readonly url: string) { if (url.includes("/api/search")) FakeEventSource.last = this; }
  addEventListener(name: string, handler: Handler) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), handler]);
  }
  close() {}
  emit(stage: string, payload: unknown) {
    for (const handler of this.listeners.get(stage) ?? []) handler({ data: JSON.stringify(payload) });
  }
}

const COVER = "/api/covers?source=oneshelf.3asq&url=https%3A%2F%2F3asq.online%2Fc.jpg";
const P_AR = { source_id: "oneshelf.3asq", listing_key: "one-piece", language: "ar", title: "ون بيس",
               url: "https://3asq.online/manga/one-piece/", cover_url: COVER };
const P_EN = { source_id: "oneshelf.mangadex", listing_key: "a1c7", language: "en", title: "One Piece",
               url: null, cover_url: null };

const result = (over: Record<string, unknown>) => ({
  work_id: null, title: "One Piece", content_type: "manga", soft: true, availability: { ar: 1 },
  provenance: [P_AR], cover_url: COVER, ...over,
});

const update = (...results: unknown[]) => ({ stage: "complete", results, source_status: {}, sources_total: 1,
                                            sources_done: 1, sources_failed: 0 });

const DETAILS = {
  work: { id: "w9", title: "One Piece", original_title: null, creator: null, description: null,
          content_type: "manga", content_type_source: "source", aliases: [] },
  shelf: { on_shelf: false, favorite: false, pinned: false, completed: false },
  follow: { following: false, preferred_source_id: null, track_id: null, language: null, last_successful_at: null },
  tracks: [{ id: "t9", source_id: "oneshelf.3asq", language: "ar", kind: "source", availability: "available",
             unit_count: 1 }],
  selected_track_id: "t9",
  units: [{ id: "u9", title: "الفصل 1", number: "1", unit_type: "chapter", volume: null, order: 1,
            release_date: null, availability: "available", url: null, downloaded: false, formats: [],
            read_state: "unread", fraction: 0, read_at: null }],
  continue_unit_id: "u9",
  cover_url: COVER,
};

beforeEach(() => vi.stubGlobal("EventSource", FakeEventSource));
afterEach(() => vi.unstubAllGlobals());

async function searchFor(results: unknown[]) {
  const user = userEvent.setup();
  await user.type(await screen.findByRole("searchbox"), "one piece{Enter}");
  FakeEventSource.last!.emit("complete", update(...results));
  return user;
}

const opened = { listing_id: "l9", work_id: "w9", track_id: "t9", details: "fetched", catalog: "refreshed" };

describe("Opening a search result", () => {
  it("links a result that already has a Work straight to it", async () => {
    mockApi([]);
    renderApp({ route: "/search" });
    await searchFor([result({ work_id: "w1", soft: false })]);
    const link = await screen.findByRole("link", { name: /one piece/i });
    expect(link).toHaveAttribute("href", "/works/w1");
  });

  it("makes a result without a Work a real button, and opens exactly its listing", async () => {
    const calls = mockApi([post("/api/listings/open", opened), get("/api/works/w9", DETAILS)]);
    renderApp({ route: "/search" });
    const user = await searchFor([result({})]);
    const button = await screen.findByRole("button", { name: /one piece/i });
    await user.click(button);
    const body = calls.find((c) => c.url === "/api/listings/open")?.body;
    expect(body).toEqual({ source_id: "oneshelf.3asq", listing_key: "one-piece", title: "ون بيس",
                           url: "https://3asq.online/manga/one-piece/", language: "ar", content_type: "manga",
                           cover_url: COVER });
    expect(await screen.findByRole("heading", { level: 1, name: "One Piece" })).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/works/w9?track_id=t9")).toBe(true);
    expect(screen.getByText("الفصل 1")).toBeInTheDocument();
  });

  it("opens with the keyboard as well", async () => {
    const calls = mockApi([post("/api/listings/open", opened), get("/api/works/w9", DETAILS)]);
    renderApp({ route: "/search" });
    const user = await searchFor([result({})]);
    (await screen.findByRole("button", { name: /one piece/i })).focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { level: 1, name: "One Piece" })).toBeInTheDocument();
    expect(calls.filter((c) => c.url === "/api/listings/open")).toHaveLength(1);
  });

  it("asks which source to open when a result was grouped from several, and binds only that one", async () => {
    const calls = mockApi([post("/api/listings/open", opened), get("/api/works/w9", DETAILS),
                           get("/api/sources", { sources: [
                             { id: "oneshelf.3asq", name: "3asq (Al-Aasheq)" }, { id: "oneshelf.mangadex", name: "MangaDex" }] })]);
    renderApp({ route: "/search" });
    const user = await searchFor([result({ availability: { ar: 1, en: 1 }, provenance: [P_AR, P_EN] })]);
    await user.click(await screen.findByRole("button", { name: /one piece/i }));
    expect(calls.some((c) => c.url === "/api/listings/open")).toBe(false);          // nothing bound yet
    const chooser = await screen.findByRole("dialog", { name: /one piece/i });
    const options = within(chooser).getAllByRole("button", { name: / · / });
    expect(options.map((o) => o.textContent)).toEqual([expect.stringMatching(/3asq.*Arabic/), expect.stringMatching(/MangaDex.*English/)]);
    await user.click(within(chooser).getByRole("button", { name: /mangadex/i }));
    const opens = calls.filter((c) => c.url === "/api/listings/open");
    expect(opens).toHaveLength(1);
    expect(opens[0]!.body).toMatchObject({ source_id: "oneshelf.mangadex", listing_key: "a1c7", language: "en" });
  });

  it("tells apart several listings from the same source by their own titles", async () => {
    const a = { ...P_EN, listing_key: "84", title: "Frankenstein; Or, The Modern Prometheus" };
    const b = { ...P_EN, listing_key: "41445", title: "Frankenstein (1831 edition)" };
    mockApi([get("/api/sources", { sources: [{ id: "oneshelf.mangadex", name: "MangaDex" }] })]);
    renderApp({ route: "/search" });
    const user = await searchFor([result({ provenance: [a, b], availability: { en: 2 } })]);
    await user.click(await screen.findByRole("button", { name: /one piece/i }));
    const chooser = await screen.findByRole("dialog", { name: /one piece/i });
    expect(within(chooser).getByRole("button", { name: /modern prometheus/i })).toBeInTheDocument();
    expect(within(chooser).getByRole("button", { name: /1831 edition/i })).toBeInTheDocument();
  });

  it("names each edition by its own id when two from one source share a title exactly", async () => {
    const a = { ...P_EN, listing_key: "84", title: "Frankenstein" };
    const b = { ...P_EN, listing_key: "41445", title: "Frankenstein" };
    mockApi([get("/api/sources", { sources: [] })]);
    renderApp({ route: "/search" });
    const user = await searchFor([result({ provenance: [a, b], availability: { en: 2 } })]);
    await user.click(await screen.findByRole("button", { name: /one piece/i }));
    const chooser = await screen.findByRole("dialog", { name: /one piece/i });
    expect(within(chooser).getByRole("button", { name: /#84$/ })).toBeInTheDocument();
    expect(within(chooser).getByRole("button", { name: /#41445$/ })).toBeInTheDocument();
  });

  it("says why a result could not be opened, and keeps the result", async () => {
    mockApi([post("/api/listings/open", { error: { code: "SOURCE_UNAVAILABLE", message: "The source is disabled." } }, 409)]);
    renderApp({ route: "/search" });
    const user = await searchFor([result({})]);
    await user.click(await screen.findByRole("button", { name: /one piece/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The source is disabled.");
    expect(screen.getByRole("button", { name: /one piece/i })).toBeInTheDocument();
  });
});

describe("Covers", () => {
  it("shows the result's cover, from this library's own address", async () => {
    mockApi([]);
    renderApp({ route: "/search" });
    await searchFor([result({})]);
    const card = await screen.findByRole("button", { name: /one piece/i });
    expect(card.querySelector("img")).toHaveAttribute("src", COVER);
  });

  it("shows the placeholder when there is no cover", async () => {
    mockApi([]);
    renderApp({ route: "/search" });
    await searchFor([result({ cover_url: null })]);
    const card = await screen.findByRole("button", { name: /one piece/i });
    expect(card.querySelector("img")).toBeNull();
    expect(card.querySelector(".workcard__blank")).not.toBeNull();
  });

  it("falls back to the placeholder when the cover cannot be loaded, and stays openable", async () => {
    mockApi([]);
    renderApp({ route: "/search" });
    await searchFor([result({})]);
    const card = await screen.findByRole("button", { name: /one piece/i });
    fireEvent.error(card.querySelector("img")!);
    expect(card.querySelector("img")).toBeNull();
    expect(card.querySelector(".workcard__blank")).not.toBeNull();
    expect(card).toBeEnabled();
  });
});
