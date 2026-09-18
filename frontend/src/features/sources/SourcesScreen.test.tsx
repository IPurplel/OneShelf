/** Master §21, §32.12: an administrative list like library catalogue cards; technical detail hidden. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SourcesScreen } from "./SourcesScreen";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

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

    expect(within(rows[0]!).queryByText(/1\.0\.0|registry|official/i)).not.toBeInTheDocument();
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

  it("says plainly when no source is installed", async () => {
    mockApi([get("/api/sources", { sources: [] })]);
    renderWithProviders(<SourcesScreen />);
    expect(await screen.findByText(/no sources are installed/i)).toBeInTheDocument();
  });

  it("offers Use My Session only for a source that can sign in", async () => {
    mockApi([get("/api/sources", SOURCES), post("/api/sources/oneshelf.webtoon/login",
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

  it("lets a package be reviewed and installed from this screen", async () => {
    mockApi([get("/api/sources", SOURCES)]);
    renderWithProviders(<SourcesScreen />);
    await screen.findAllByRole("listitem");

    expect(screen.getByLabelText(/choose an \.osp package/i)).toBeInTheDocument();
  });
});
