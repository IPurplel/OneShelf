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

  const entry = (id: string, title: string) => ({ work_id: id, title, added_at: "", is_favorite: false, is_pinned: false,
                                                   completed_at: null, releases_since_completion: 0, last_read_at: null,
                                                   read_fraction: 0, total_bytes: 0 });

  /** The shelf pick, answered from `next`; every request the panel makes is kept in `asked`. */
  function shelfPicks(next: { current: unknown }) {
    const asked: URLSearchParams[] = [];
    stubFeeds({ "oneshelf.3asq/latest/1": page(1, [item("a", "Alpha")], false) }, [
      { match: (url) => { if (!url.startsWith("/api/discover/random?from=library")) return false;
                          asked.push(new URLSearchParams(url.split("?")[1])); return true; },
        get payload() { return next.current; } },
    ]);
    return asked;
  }
  const panelOf = () => screen.getByRole("heading", { name: "What should I read now?" }).closest("section") as HTMLElement;

  it("suggests a work from the shelf that is not started, or says there is none", async () => {
    const next: { current: unknown } = { current: { item: entry("w1", "Waiting Book"), reason: { kind: "fresh" }, more: true } };
    const asked = shelfPicks(next);
    const user = userEvent.setup();
    renderWithProviders(<DiscoverScreen />);
    await screen.findByText("Alpha");
    const panel = panelOf();
    await user.click(within(panel).getByRole("button", { name: "Not started yet" }));
    await user.click(within(panel).getByRole("button", { name: "Pick one" }));
    expect(await within(panel).findByRole("link", { name: /Waiting Book/ })).toHaveAttribute("href", "/works/w1");
    expect(within(panel).getByText("On your shelf, not started yet.")).toBeInTheDocument();
    expect(asked[0]!.get("mood")).toBe("fresh");

    next.current = { item: null, reason: null, more: false };
    await user.click(within(panel).getByRole("button", { name: "Another" }));
    await waitFor(() => expect(within(panel).getByText("Everything on your shelf is started or finished.")).toBeInTheDocument());
  });

  it("asks for the mood chosen, says what made the pick, and never offers the same work twice", async () => {
    const next: { current: unknown } = { current: { item: entry("w1", "Nearly Done"), reason: { kind: "short", remaining: 2 }, more: true } };
    const asked = shelfPicks(next);
    const user = userEvent.setup();
    renderWithProviders(<DiscoverScreen />);
    await screen.findByText("Alpha");
    const panel = panelOf();
    // The first mood is selected to begin with.
    expect(within(panel).getByRole("button", { name: "Pick up where I left off" })).toHaveAttribute("aria-pressed", "true");

    await user.click(within(panel).getByRole("button", { name: "Something short" }));
    expect(within(panel).getByRole("button", { name: "Something short" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(panel).getByRole("button", { name: "Pick one" }));
    expect(await within(panel).findByText("A short one: 2 left to read.")).toBeInTheDocument();
    expect(asked[0]!.get("mood")).toBe("short");
    expect(asked[0]!.get("exclude")).toBeNull();

    next.current = { item: entry("w2", "Also Short"), reason: { kind: "short", remaining: 4 }, more: false };
    await user.click(within(panel).getByRole("button", { name: "Another" }));
    expect(await within(panel).findByRole("link", { name: /Also Short/ })).toBeInTheDocument();
    expect(asked[1]!.get("exclude")).toBe("w1");
    // Nothing else fits: it says so, and does not offer a button that would only repeat.
    expect(within(panel).getByText("That's all for this mood.")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Another" })).toBeDisabled();
  });

  it.each([
    ["Pick up where I left off", { kind: "continue", remaining: 5 }, "You started this. 5 left to read."],
    ["Something light", { kind: "light", content_type: "manhwa" }, "A comic from your shelf."],
    ["Pick up where I left off", { kind: "continue" }, "You started this."],     // one file: no count of chapters
    ["Something short", { kind: "short" }, "A short one."],
  ])("explains a %s pick in plain words", async (mood, reason, text) => {
    shelfPicks({ current: { item: entry("w1", "Some Book"), reason, more: true } });
    const user = userEvent.setup();
    renderWithProviders(<DiscoverScreen />);
    await screen.findByText("Alpha");
    const panel = panelOf();
    await user.click(within(panel).getByRole("button", { name: mood }));
    await user.click(within(panel).getByRole("button", { name: "Pick one" }));
    expect(await within(panel).findByText(text)).toBeInTheDocument();
  });

  it("says why there is nothing, mood by mood, and starts over when the mood changes", async () => {
    const next: { current: unknown } = { current: { item: entry("w1", "Some Book"), reason: { kind: "short", remaining: 2 }, more: true } };
    shelfPicks(next);
    const user = userEvent.setup();
    renderWithProviders(<DiscoverScreen />);
    await screen.findByText("Alpha");
    const panel = panelOf();
    next.current = { item: null, reason: null, more: false };
    await user.click(within(panel).getByRole("button", { name: "Pick one" }));
    expect(await within(panel).findByText("Nothing is in progress yet. Start a book and it will wait here.")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Something light" }));
    expect(within(panel).queryByText(/Nothing is in progress/)).toBeNull();      // a new mood, a clean slate
    await user.click(within(panel).getByRole("button", { name: "Pick one" }));
    expect(await within(panel).findByText("There is no comic on your shelf to pick from.")).toBeInTheDocument();
  });
});
