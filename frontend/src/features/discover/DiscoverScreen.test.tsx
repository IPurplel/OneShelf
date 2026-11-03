/** Discover (docs/adr/0004-discover.md): a source's own lists, a page at a time, and two honest surprises. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DiscoverScreen } from "./DiscoverScreen";
import { renderWithProviders } from "@/test/render";
import { get, mockApi } from "@/test/http";

const ASQ = { source_id: "oneshelf.3asq", name: "3asq", feeds: ["latest", "trending"], category: "manga", languages: ["ar"] };
const DEX = { source_id: "oneshelf.mangadex", name: "MangaDex", feeds: ["latest"], category: "manga", languages: ["en"] };

const item = (key: string, title: string, over: Record<string, unknown> = {}) => ({
  work_id: null, title, content_type: "manga", soft: true, availability: { ar: 1 }, cover_url: null, on_shelf: false,
  provenance: [{ source_id: "oneshelf.3asq", listing_key: key, language: "ar", title, url: null }], ...over,
});

const page = (n: number, items: unknown[], has_more: boolean) =>
  ({ source_id: "oneshelf.3asq", kind: "latest", page: n, has_more, cached: false, items });

afterEach(() => vi.unstubAllGlobals());

/** Answers each feed page by its query, so the test sees exactly which page the screen asked for. */
function stubFeeds(pages: Record<string, unknown>, extra: Parameters<typeof mockApi>[0] = []) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push(url);
    if (url.startsWith("/api/discover/sources")) return json({ sources: [ASQ, DEX] });
    if (url.startsWith("/api/discover/list")) {
      const query = new URLSearchParams(url.split("?")[1]);
      const found = pages[`${query.get("source")}/${query.get("kind")}/${query.get("page")}`];
      return found === undefined ? json({ error: { code: "SOURCE_FAILED", message: "The source did not answer." } }, 502)
                                 : json(found);
    }
    const route = extra.find((candidate) => candidate.match(url));
    return route ? json(route.payload, route.status) : json({ error: { code: "NOT_STUBBED", message: url } }, 404);
  }));
  return calls;
}

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

describe("Discover", () => {
  it("reads a source's list one page at a time and says when it ends", async () => {
    const calls = stubFeeds({
      "oneshelf.3asq/latest/1": page(1, [item("a", "Alpha"), item("b", "Beta", { on_shelf: true })], true),
      "oneshelf.3asq/latest/2": page(2, [item("c", "Gamma")], false),
    });
    const user = userEvent.setup();
    renderWithProviders(<DiscoverScreen />);

    const list = await screen.findByRole("list", { name: "3asq · Latest" });
    expect(within(list).getByText("Alpha")).toBeInTheDocument();
    expect(within(list).getByText("On your shelf")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await within(list).findByText("Gamma")).toBeInTheDocument();
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("That's the end of this list.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    expect(calls.filter((url) => url.startsWith("/api/discover/list"))).toEqual([
      "/api/discover/list?source=oneshelf.3asq&kind=latest&page=1",
      "/api/discover/list?source=oneshelf.3asq&kind=latest&page=2",
    ]);
  });

  it("switches source and list, offering only the lists a source has", async () => {
    stubFeeds({
      "oneshelf.3asq/latest/1": page(1, [item("a", "Alpha")], false),
      "oneshelf.3asq/trending/1": page(1, [item("p", "Popular One")], false),
      "oneshelf.mangadex/latest/1": page(1, [item("m", "Dex Work")], false),
    });
    const user = userEvent.setup();
    renderWithProviders(<DiscoverScreen />);
    await screen.findByText("Alpha");

    await user.click(screen.getByRole("button", { name: "Popular" }));
    expect(await screen.findByText("Popular One")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Popular" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "MangaDex" }));
    expect(await screen.findByText("Dex Work")).toBeInTheDocument();
    // MangaDex has only Latest, so there is no list to choose between.
    expect(screen.queryByRole("button", { name: "Popular" })).toBeNull();
  });

  it("says plainly when a list fails, and retries it", async () => {
    const pages: Record<string, unknown> = {};
    stubFeeds(pages);
    const user = userEvent.setup();
    renderWithProviders(<DiscoverScreen />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    pages["oneshelf.3asq/latest/1"] = page(1, [item("a", "Alpha")], false);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Alpha")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each(["en", "ar"] as const)("points to Sources when nothing can be browsed in %s", async (language) => {
    mockApi([get("/api/discover/sources", { sources: [] })]);
    renderWithProviders(<DiscoverScreen />, { language });
    const link = await screen.findByRole("link", { name: language === "en" ? "Sources" : "المصادر" });
    expect(link).toHaveAttribute("href", "/sources");
    // With nothing to browse, a surprise from the sources has nothing to draw from; the shelf one still works.
    const [sources, shelf] = screen.getAllByRole("button", { name: language === "en" ? "Pick one" : "اختر لي" });
    expect(sources).toBeDisabled();
    expect(shelf).toBeEnabled();
  });

  it("surprises from the sources and says which list the work came from", async () => {
    stubFeeds({ "oneshelf.3asq/latest/1": page(1, [item("a", "Alpha")], false) }, [
      { match: (url) => url.startsWith("/api/discover/random?from=sources"),
        payload: { item: item("z", "Zeta"), reason: { source_id: "oneshelf.3asq", source_name: "3asq", kind: "trending" } } },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<DiscoverScreen />);
    await screen.findByText("Alpha");
    const panel = screen.getByRole("heading", { name: "Surprise me" }).closest("section")!;
    await user.click(within(panel as HTMLElement).getByRole("button", { name: "Pick one" }));
    expect(await within(panel as HTMLElement).findByText("Zeta")).toBeInTheDocument();
    expect(within(panel as HTMLElement).getByText("From 3asq's Popular list.")).toBeInTheDocument();
    expect(within(panel as HTMLElement).getByRole("button", { name: "Another" })).toBeEnabled();
  });

  it("suggests a work from the shelf that is not started, or says there is none", async () => {
    let next: unknown = { item: { work_id: "w1", title: "Waiting Book", added_at: "", is_favorite: false, is_pinned: false,
                                  completed_at: null, releases_since_completion: 0, last_read_at: null, read_fraction: 0,
                                  total_bytes: 0 },
                          reason: { kind: "not_started" } };
    stubFeeds({ "oneshelf.3asq/latest/1": page(1, [item("a", "Alpha")], false) }, [
      { match: (url) => url.startsWith("/api/discover/random?from=library"), get payload() { return next; } },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<DiscoverScreen />);
    await screen.findByText("Alpha");
    const panel = screen.getByRole("heading", { name: "What should I read from my shelf?" }).closest("section") as HTMLElement;
    await user.click(within(panel).getByRole("button", { name: "Pick one" }));
    expect(await within(panel).findByRole("link", { name: /Waiting Book/ })).toHaveAttribute("href", "/works/w1");
    expect(within(panel).getByText("On your shelf, not started yet.")).toBeInTheDocument();

    next = { item: null, reason: null };
    await user.click(within(panel).getByRole("button", { name: "Another" }));
    await waitFor(() => expect(within(panel).getByText("Everything on your shelf is started or finished.")).toBeInTheDocument());
  });
});
