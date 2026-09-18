/** Master §32.14, §45: a readable document, categories beside the panel, progressive disclosure. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsScreen } from "./SettingsScreen";
import { renderWithProviders } from "@/test/render";
import { get, mockApi } from "@/test/http";

const AUTH = {
  canonical_hostname: null, remote_enabled: false, passkeys: [], sessions: [],
  recovery: { configured: false, created_at: null, last_used_at: null },
  access: "loopback", network: { trusted_networks: [], trusted_proxies: [], gateway_warning: null },
  session_lifetimes: ["7d", "30d", "90d", "1y", "manual"],
};

const STORAGE = { roots: [{ id: "r1", name: "Library", path: "/library", available: true, free: 1e10, total: 2e10,
                            reserve: 5e8, is_default: true, state: "ok" }], missing: 0 };

afterEach(() => vi.unstubAllGlobals());

describe("Settings", () => {
  it("offers the Master's categories", async () => {
    mockApi([get("/api/auth/state", AUTH), get("/api/storage", STORAGE)]);
    renderWithProviders(<SettingsScreen />);

    const nav = await screen.findByRole("tablist", { name: /settings/i });
    expect(within(nav).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "General", "Reader", "Downloads", "Storage", "Sources", "Notifications", "Backup", "Remote access",
      "Advanced", "Developer",
    ]);
  });

  it("shows storage locations with their free space and reserve", async () => {
    mockApi([get("/api/auth/state", AUTH), get("/api/storage", STORAGE)]);
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />);
    await screen.findByRole("tablist", { name: /settings/i });

    await user.click(screen.getByRole("tab", { name: "Storage" }));
    const panel = await screen.findByRole("tabpanel");
    expect(within(panel).getByText("Library")).toBeInTheDocument();
    expect(within(panel).getByText(/free of/i)).toBeInTheDocument();      // space available
    expect(within(panel).getByText(/kept free/i)).toBeInTheDocument();    // the reserve OneShelf keeps
  });

  it("describes remote access honestly when it is not set up", async () => {
    mockApi([get("/api/auth/state", AUTH), get("/api/storage", STORAGE)]);
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />);
    await screen.findByRole("tablist", { name: /settings/i });

    await user.click(screen.getByRole("tab", { name: "Remote access" }));
    const panel = await screen.findByRole("tabpanel");
    expect(within(panel).getByText(/not set up/i)).toBeInTheDocument();
    expect(within(panel).queryByText(/passkey registered/i)).not.toBeInTheDocument();
  });

  it("keeps developer tools out of the way until asked", async () => {
    mockApi([get("/api/auth/state", AUTH), get("/api/storage", STORAGE)]);
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />);
    await screen.findByRole("tablist", { name: /settings/i });

    expect(screen.queryByText(/adapter generator/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Developer" }));
    expect(within(await screen.findByRole("tabpanel")).getByText(/adapter generator/i)).toBeInTheDocument();
  });

  it("uses no shelves on an operational screen", async () => {
    mockApi([get("/api/auth/state", AUTH), get("/api/storage", STORAGE)]);
    renderWithProviders(<SettingsScreen />);
    await screen.findByRole("tablist", { name: /settings/i });
    expect(document.querySelector(".shelf__plank")).toBeNull();
  });
});
