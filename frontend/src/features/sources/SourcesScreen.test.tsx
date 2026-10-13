/** Master §21, §32.12: an administrative list like library catalogue cards; technical detail hidden. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SourcesScreen } from "./SourcesScreen";
import { renderWithProviders } from "@/test/render";
import { del, get, mockApi, post } from "@/test/http";

const SOURCES = {
  sources: [
    { id: "oneshelf.mangadex", name: "MangaDex", state: "active", version: "1.0.0", trust_label: "official",
      channel: "registry", capabilities: ["search", "work", "catalog", "reader"], auth_available: false,
      session_state: "none" },
    { id: "oneshelf.webtoon", name: "WEBTOON", state: "disabled", version: "1.0.0", trust_label: "official",
      channel: "upload", capabilities: ["work", "catalog"], auth_available: true, session_state: "expired" },
  ],
};

const HEALTH = { source_id: "oneshelf.mangadex", state: "healthy", last_successful_at: "2026-09-18T09:00:00+00:00",
                 consecutive_failures: 0, capabilities: {} };

afterEach(() => vi.unstubAllGlobals());

describe("Sources", () => {
  it.each([
    ["en", "More about MangaDex", "More about WEBTOON"],
    ["ar", "المزيد عن MangaDex", "المزيد عن WEBTOON"],
  ] as const)("names each installed source's More action in %s", async (language, first, second) => {
    mockApi([get("/api/sources", SOURCES)]);
    renderWithProviders(<SourcesScreen />, { language });
    const installed = await screen.findByRole("region", { name: language === "ar" ? "المصادر المثبّتة" : "Installed sources" });
    const rows = within(installed).getAllByRole("listitem");
    expect(within(rows[0]!).getByRole("button", { name: first })).toBeInTheDocument();
    expect(within(rows[1]!).getByRole("button", { name: second })).toBeInTheDocument();
  });

  it("browses installed sources by category and language, counting multilingual matches", async () => {
    mockApi([get("/api/sources", { sources: [
      { ...SOURCES.sources[0], category: "Manga", languages: ["EN"] },
      { ...SOURCES.sources[1], category: "Manga", languages: ["Multi"] },
      { ...SOURCES.sources[0], id: "books", name: "Arabic Books", category: "Books", languages: ["AR"] },
      { ...SOURCES.sources[0], id: "unknown", name: "Unlabeled Source", category: null, languages: [] },
      { ...SOURCES.sources[0], id: "removed", name: "Removed Source", state: "uninstalled", category: "Journal", languages: ["FR"] },
    ] })]);
    const user = userEvent.setup();
    renderWithProviders(<SourcesScreen />);
    const installed = await screen.findByRole("region", { name: "Installed sources" });
    const categories = within(installed).getByRole("group", { name: "Categories" });
    const languages = within(installed).getByRole("group", { name: "Languages" });
    expect(within(installed).getByRole("status")).toHaveTextContent("4 of 4");
    expect(within(categories).getByRole("button", { name: "Manga · 2" })).toHaveAttribute("aria-pressed", "false");
    expect(within(languages).getByRole("button", { name: "English · 2" })).toBeInTheDocument();
    expect(within(languages).getByRole("button", { name: "Arabic · 2" })).toBeInTheDocument();
    expect(within(categories).queryByRole("button", { name: /journal/i })).toBeNull();
    await user.click(within(categories).getByRole("button", { name: "Manga · 2" }));
    await user.click(within(languages).getByRole("button", { name: "English · 2" }));
    expect(within(installed).getAllByRole("listitem")).toHaveLength(2);
    expect(within(installed).getByText("WEBTOON")).toBeInTheDocument();
    expect(within(installed).getByRole("status")).toHaveTextContent("2 of 4");
    await user.click(within(languages).getByRole("button", { name: "Arabic · 2" }));
    expect(within(installed).getAllByRole("listitem")).toHaveLength(1);
    expect(within(installed).getByText("WEBTOON")).toBeInTheDocument();
    expect(within(installed).queryByText("MangaDex")).toBeNull();
    await user.click(within(languages).getByRole("button", { name: "All languages" }));
    expect(within(installed).getAllByRole("listitem")).toHaveLength(2);
  });

  it("keeps unlabeled sources browseable and distinguishes filtered emptiness from no installs", async () => {
    mockApi([get("/api/sources", { sources: [
      { ...SOURCES.sources[0], category: "Manga", languages: ["EN"] },
      { ...SOURCES.sources[1], category: null, languages: [] },
    ] })]);
    const user = userEvent.setup();
    renderWithProviders(<SourcesScreen />);
    const installed = await screen.findByRole("region", { name: "Installed sources" });
    expect(within(installed).getByText("WEBTOON")).toBeInTheDocument();
    const categories = within(installed).getByRole("group", { name: "Categories" });
    const languages = within(installed).getByRole("group", { name: "Languages" });
    await user.click(within(categories).getByRole("button", { name: "Unknown category · 1" }));
    expect(within(installed).getByText("WEBTOON")).toBeInTheDocument();
    await user.click(within(languages).getByRole("button", { name: "Unknown language · 1" }));
    expect(within(installed).getByRole("status")).toHaveTextContent("1 of 2");
    await user.click(within(categories).getByRole("button", { name: "Manga · 1" }));
    expect(within(installed).getByText("No installed sources match these filters.")).toBeInTheDocument();
    expect(within(installed).queryByText("No sources are installed yet.")).toBeNull();
    expect(within(installed).getByRole("status")).toHaveTextContent("0 of 2");
  });

  it("localizes installed browsing controls and results in Arabic", async () => {
    mockApi([get("/api/sources", { sources: [
      { ...SOURCES.sources[0], category: "Manga", languages: ["AR"] },
      { ...SOURCES.sources[1], category: "Books", languages: ["EN"] },
    ] })]);
    const user = userEvent.setup();
    renderWithProviders(<SourcesScreen />, { language: "ar" });
    const installed = await screen.findByRole("region", { name: "المصادر المثبّتة" });
    const categories = within(installed).getByRole("group", { name: "التصنيفات" });
    const languages = within(installed).getByRole("group", { name: "اللغات" });
    await user.click(within(categories).getByRole("button", { name: "مانجا · 1" }));
    await user.click(within(languages).getByRole("button", { name: "الإنجليزية · 1" }));
    expect(within(installed).getByText("لا توجد مصادر مثبّتة تطابق هذه المرشحات.")).toBeInTheDocument();
    expect(within(installed).getByRole("status")).toHaveTextContent("0 من أصل 2");
  });

  it.each(["en", "ar"] as const)("offers rollback only for a source with a previous version in %s", async (language) => {
    const calls = mockApi([get("/api/sources", { sources: [
      { ...SOURCES.sources[0], can_rollback: false },
      { ...SOURCES.sources[1], can_rollback: true },
    ] }), post("/api/sources/oneshelf.webtoon/rollback", { id: "oneshelf.webtoon", state: "active" })]);
    const user = userEvent.setup();
    renderWithProviders(<SourcesScreen />, { language });
    const rows = await screen.findAllByRole("listitem");
    await user.click(within(rows[0]!).getByRole("button"));
    let drawer = await screen.findByRole("dialog");
    expect(within(drawer).queryByRole("button", { name: /roll back|العودة إلى الإصدار السابق/i })).toBeNull();
    await user.click(within(drawer).getByRole("button", { name: /close|إغلاق/i }));
    await user.click(within(rows[1]!).getByRole("button"));
    drawer = await screen.findByRole("dialog");
    await user.click(within(drawer).getByRole("button", { name: /roll back|العودة إلى الإصدار السابق/i }));
    expect(calls.some(call => call.url === "/api/sources/oneshelf.webtoon/rollback" && call.method === "POST")).toBe(true);
  });

  it("uses Arabic labels for capabilities and technical source details", async () => {
    mockApi([get("/api/sources", SOURCES)]);
    const user = userEvent.setup();
    renderWithProviders(<SourcesScreen />, { language: "ar" });
    const rows = await screen.findAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("بحث");
    expect(rows[0]).not.toHaveTextContent("search · work");
    await user.click(within(rows[0]!).getByRole("button", { name: /المزيد/i }));
    const dialog = screen.getByRole("dialog", { name: "MangaDex" });
    expect(within(dialog).getByText("السجلّ")).toBeInTheDocument();
    expect(within(dialog).getByText("رسمي")).toBeInTheDocument();
  });
  it("lists each source with what it does and how it is doing", async () => {
    mockApi([get("/api/sources", SOURCES), get("/api/sources/oneshelf.mangadex/health/state", HEALTH)]);
    renderWithProviders(<SourcesScreen />);

    const rows = await screen.findAllByRole("listitem");
    expect(within(rows[0]!).getByText("MangaDex")).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/search/i)).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/disabled/i)).toBeInTheDocument();
  });

  it("says when a source needs reconnecting rather than hiding it", async () => {
    mockApi([get("/api/sources", SOURCES)]);
    renderWithProviders(<SourcesScreen />);
    const rows = await screen.findAllByRole("listitem");
    expect(within(rows[1]!).getByText(/reconnect/i)).toBeInTheDocument();
  });

  it("keeps technical detail behind More rather than on the list", async () => {
    mockApi([get("/api/sources", SOURCES)]);
    const user = userEvent.setup();
    renderWithProviders(<SourcesScreen />);
    const rows = await screen.findAllByRole("listitem");

    // Where a source came from is a plain label on the row (release requirement REL-13); the version,
    // the raw channel and the trust token stay behind More.
    expect(within(rows[0]!).queryByText(/1\.0\.0/)).not.toBeInTheDocument();
    expect(within(rows[0]!).getByText("Official · Registry")).toBeInTheDocument();
    expect(within(rows[0]!).queryByText(/^registry$|^official$/i)).not.toBeInTheDocument();
    await user.click(within(rows[0]!).getByRole("button", { name: /more/i }));
    const panel = await screen.findByRole("dialog", { name: /mangadex/i });
    expect(within(panel).getByText(/1\.0\.0/)).toBeInTheDocument();
    expect(within(panel).getByText(/registry/i)).toBeInTheDocument();
  });

  it("enables and disables a source through the library", async () => {
    const calls = mockApi([
      get("/api/sources", SOURCES),
      post("/api/sources/oneshelf.webtoon/enable", { id: "oneshelf.webtoon", state: "active" }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<SourcesScreen />);
    const rows = await screen.findAllByRole("listitem");

    await user.click(within(rows[1]!).getByRole("button", { name: /more/i }));
    const panel = await screen.findByRole("dialog", { name: /webtoon/i });
    await user.click(within(panel).getByRole("button", { name: /^enable$/i }));
    expect(calls.some((call) => call.url === "/api/sources/oneshelf.webtoon/enable")).toBe(true);
  });

  it("marks the sources that ship with OneShelf, and only those", async () => {
    // Release requirement: the official adapters arrive with the install. Saying so on the row is how a
    // person knows they did not have to add them — and a source they uploaded is not labelled that way.
    mockApi([get("/api/sources", { sources: [
      { ...SOURCES.sources[0], channel: "bundled" },
      { ...SOURCES.sources[1], channel: "upload", trust_label: "local" },
    ] })]);
    renderWithProviders(<SourcesScreen />);
    const rows = await screen.findAllByRole("listitem");
    expect(within(rows[0]!).getByText("Official · Bundled")).toBeInTheDocument();
    expect(within(rows[1]!).queryByText("Official · Bundled")).toBeNull();
  });

  it("labels a source from the Registry or from a file for what it is", async () => {
    mockApi([get("/api/sources", { sources: [
      { ...SOURCES.sources[0], channel: "registry", trust_label: "community" },
      { ...SOURCES.sources[1], channel: "upload", trust_label: "local" },
    ] })]);
    renderWithProviders(<SourcesScreen />);
    const rows = await screen.findAllByRole("listitem");
    expect(within(rows[0]!).getByText("Community · Registry")).toBeInTheDocument();
    expect(within(rows[0]!).queryByText(/^official/i)).toBeNull();
    expect(within(rows[1]!).getByText("Local upload")).toBeInTheDocument();
  });

  it("keeps trust level and delivery channel apart for Verified Community sources", async () => {
    mockApi([get("/api/sources", { sources: [
      { ...SOURCES.sources[0], channel: "registry", trust_label: "verified_community" },
    ] })]);
    renderWithProviders(<SourcesScreen />);
    const rows = await screen.findAllByRole("listitem");
    expect(within(rows[0]!).getByText("Verified Community · Registry")).toBeInTheDocument();
  });

  it("removes a source only after saying what stays, and that it will not come back by itself", async () => {
    const calls = mockApi([
      get("/api/sources", SOURCES),
      del("/api/sources/oneshelf.mangadex", { id: "oneshelf.mangadex", state: "uninstalled" }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<SourcesScreen />);
    const rows = await screen.findAllByRole("listitem");

    await user.click(within(rows[0]!).getByRole("button", { name: /more/i }));
    await user.click(await screen.findByRole("button", { name: /remove this source/i }));
    const confirm = await screen.findByRole("dialog", { name: /remove mangadex/i });
    expect(within(confirm).getByText(/reading progress stay exactly as they are/i)).toBeInTheDocument();
    expect(within(confirm).getByText(/source registry/i)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    await user.click(within(confirm).getByRole("button", { name: /remove source/i }));
    expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/sources/oneshelf.mangadex")).toBe(true);
  });

  it("shows installed sources, the Source Registry and install from file as their own sections", async () => {
    mockApi([get("/api/sources", SOURCES), get("/api/registry", { configured: false, plugins: [] })]);
    renderWithProviders(<SourcesScreen />);
    expect(await screen.findByRole("heading", { name: /installed sources/i })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /^source registry$/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /install from file/i })).toBeInTheDocument();
  });

  it("keeps the installed list usable when the Registry cannot be reached", async () => {
    mockApi([get("/api/sources", SOURCES), get("/api/registry",
      { error: { code: "REGISTRY_UNAVAILABLE", message: "registry unavailable" } }, 502)]);
    renderWithProviders(<SourcesScreen />);
    expect(await screen.findByText(/installed sources keep working/i)).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("does not list a removed source as installed — the Registry offers it again instead", async () => {
    mockApi([get("/api/sources", { sources: [
      SOURCES.sources[0],
      { ...SOURCES.sources[1], state: "uninstalled", version: null, capabilities: [] },
    ] })]);
    renderWithProviders(<SourcesScreen />);
    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(screen.queryByText("WEBTOON")).toBeNull();
    expect(screen.queryByText(/sources\.state/)).toBeNull();
  });

  it("says plainly when no source is installed", async () => {
    mockApi([get("/api/sources", { sources: [] })]);
    renderWithProviders(<SourcesScreen />);
    expect(await screen.findByText(/no sources are installed/i)).toBeInTheDocument();
  });

  it("offers Use My Session only for a source that can sign in", async () => {
    mockApi([get("/api/sources", { sources: [SOURCES.sources[0], { ...SOURCES.sources[1], state: "active" }] }),
      post("/api/sources/oneshelf.webtoon/login",
                                                { login_id: "l1", status: "open" })]);
    const user = userEvent.setup();
    renderWithProviders(<SourcesScreen />);
    const rows = await screen.findAllByRole("listitem");

    await user.click(within(rows[0]!).getByRole("button", { name: /more/i }));
    expect(screen.queryByRole("button", { name: /use my session/i })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");

    await user.click(within(rows[1]!).getByRole("button", { name: /more/i }));
    await user.click(screen.getByRole("button", { name: /use my session/i }));
    expect(await screen.findByRole("dialog", { name: /sign in/i })).toBeInTheDocument();
  });

  it("does not offer sign-in while a source is disabled", async () => {
    mockApi([get("/api/sources", SOURCES)]);
    const user = userEvent.setup();
    renderWithProviders(<SourcesScreen />);
    const rows = await screen.findAllByRole("listitem");
    await user.click(within(rows[1]!).getByRole("button", { name: /more/i }));
    const drawer = screen.getByRole("dialog", { name: "WEBTOON" });
    expect(within(drawer).getByRole("button", { name: /^enable$/i })).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /use my session/i })).toBeNull();
  });

  it("lets a package be reviewed and installed from this screen", async () => {
    mockApi([get("/api/sources", SOURCES)]);
    renderWithProviders(<SourcesScreen />);
    await screen.findAllByRole("listitem");

    expect(screen.getByLabelText(/choose an \.osp package/i)).toBeInTheDocument();
  });
});
