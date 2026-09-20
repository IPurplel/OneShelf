/** Master §32.14, §45: a readable document, categories beside the panel, progressive disclosure. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsScreen } from "./SettingsScreen";
import { renderWithProviders } from "@/test/render";
import { del, get, mockApi, post } from "@/test/http";

const AUTH = {
  canonical_hostname: null, remote_enabled: false, passkeys: [], sessions: [],
  recovery: { configured: false, created_at: null, last_used_at: null },
  access: "loopback", network: { trusted_networks: [], trusted_proxies: [], gateway_warning: null },
  session_lifetimes: ["7d", "30d", "90d", "1y", "manual"],
};

const READER = { auto_mark_read_threshold: 0.97, smart_controls_hide_after_ms: 3000,
                 remember_per_work: true, preload_next: 7, preload_previous: 4 };

const DOWNLOADS = { auto_download: { enabled: false, mode: "current", read_ahead: 5, threshold: 0.12 },
                    keep_partial_on_cancel: false,
                    extraction: { method: null, mode: "preferred_ask", fallback_order: [] } };

const NOTIFY = { source_recovered: false };

const DIAGNOSTICS = { entries: 42, size_bytes: 1_200_000, oldest_day: "20260913", max_bytes: 104857600,
                      max_age_days: 7, directory: "/data/diagnostics" };

const STORAGE = { roots: [{ id: "r1", name: "Library", path: "/library", available: true, free: 1e10, total: 2e10,
                            reserve: 5e8, is_default: true, state: "ok" }], missing: 0 };

afterEach(() => vi.unstubAllGlobals());

describe("Settings", () => {
  it("offers the Master's categories", async () => {
    mockApi([get("/api/auth/state", AUTH), get("/api/storage", STORAGE), get("/api/sources", { sources: [] }),
             get("/api/reader/settings", READER), get("/api/downloads/settings", DOWNLOADS),
             get("/api/notifications/settings", NOTIFY), get("/api/diagnostics", DIAGNOSTICS)]);
    renderWithProviders(<SettingsScreen />);

    const nav = await screen.findByRole("tablist", { name: /settings/i });
    expect(within(nav).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "General", "Reader", "Downloads", "Storage", "Sources", "Notifications", "Backup", "Remote access",
      "Advanced", "Developer",
    ]);
  });

  it("shows storage locations with their free space and reserve", async () => {
    mockApi([get("/api/auth/state", AUTH), get("/api/storage", STORAGE), get("/api/sources", { sources: [] }),
             get("/api/reader/settings", READER), get("/api/downloads/settings", DOWNLOADS),
             get("/api/notifications/settings", NOTIFY), get("/api/diagnostics", DIAGNOSTICS)]);
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
    mockApi([get("/api/auth/state", AUTH), get("/api/storage", STORAGE), get("/api/sources", { sources: [] }),
             get("/api/reader/settings", READER), get("/api/downloads/settings", DOWNLOADS),
             get("/api/notifications/settings", NOTIFY), get("/api/diagnostics", DIAGNOSTICS)]);
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />);
    await screen.findByRole("tablist", { name: /settings/i });

    await user.click(screen.getByRole("tab", { name: "Remote access" }));
    const panel = await screen.findByRole("tabpanel");
    expect(within(panel).getByText(/not set up/i)).toBeInTheDocument();
    expect(within(panel).queryByText(/passkey registered/i)).not.toBeInTheDocument();
  });

  it("keeps developer tools out of the way until asked", async () => {
    mockApi([get("/api/auth/state", AUTH), get("/api/storage", STORAGE), get("/api/sources", { sources: [] }),
             get("/api/reader/settings", READER), get("/api/downloads/settings", DOWNLOADS),
             get("/api/notifications/settings", NOTIFY), get("/api/diagnostics", DIAGNOSTICS)]);
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />);
    await screen.findByRole("tablist", { name: /settings/i });

    expect(screen.queryByText(/adapter generator/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Developer" }));
    expect(within(await screen.findByRole("tabpanel")).getByText(/adapter generator/i)).toBeInTheDocument();
  });

  it("uses no shelves on an operational screen", async () => {
    mockApi([get("/api/auth/state", AUTH), get("/api/storage", STORAGE), get("/api/sources", { sources: [] }),
             get("/api/reader/settings", READER), get("/api/downloads/settings", DOWNLOADS),
             get("/api/notifications/settings", NOTIFY), get("/api/diagnostics", DIAGNOSTICS)]);
    renderWithProviders(<SettingsScreen />);
    await screen.findByRole("tablist", { name: /settings/i });
    expect(document.querySelector(".shelf__plank")).toBeNull();
  });

  // §32.14: every category holds its settings. §45: what a reader needs first, the technical knobs
  // behind disclosure. Nothing here is invented — each control writes a setting the backend honours.
  const ALL = [get("/api/auth/state", AUTH), get("/api/storage", STORAGE), get("/api/sources", { sources: [] }),
               get("/api/reader/settings", READER), get("/api/downloads/settings", DOWNLOADS),
               get("/api/notifications/settings", NOTIFY), get("/api/diagnostics", DIAGNOSTICS)];

  it("has no category left saying it is coming later", async () => {
    mockApi(ALL);
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />);
    await screen.findByRole("tablist", { name: /settings/i });

    for (const name of ["General", "Reader", "Downloads", "Storage", "Sources", "Notifications",
                        "Backup", "Remote access", "Advanced", "Developer"]) {
      await user.click(screen.getByRole("tab", { name }));
      const panel = await screen.findByRole("tabpanel");
      expect(panel).not.toHaveTextContent(/coming with/i);
      expect(panel.textContent?.trim().length ?? 0).toBeGreaterThan(20);
    }
  });

  it("keeps the technical knobs behind disclosure, and writes what the reader chooses", async () => {
    const calls = mockApi([...ALL, post("/api/reader/settings", { ...READER, preload_next: 7 })]);
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />);
    await screen.findByRole("tablist", { name: /settings/i });

    await user.click(screen.getByRole("tab", { name: "Reader" }));
    const panel = await screen.findByRole("tabpanel");
    expect(within(panel).getByRole("radiogroup", { name: /mode/i })).toBeInTheDocument();
    expect(within(panel).queryByRole("spinbutton", { name: /pages ahead/i })).not.toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: /advanced/i }));
    const ahead = await within(panel).findByRole("spinbutton", { name: /pages ahead/i });
    await user.clear(ahead);
    await user.type(ahead, "9");
    await user.tab();

    const write = calls.find((call) => call.method === "POST" && call.url === "/api/reader/settings");
    expect(write?.body).toEqual({ preload_next: 9 });
  });

  it("offers auto-download as the Master defines it: off, and with its own reach", async () => {
    const calls = mockApi([...ALL, post("/api/downloads/settings", DOWNLOADS)]);
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />);
    await screen.findByRole("tablist", { name: /settings/i });

    await user.click(screen.getByRole("tab", { name: "Downloads" }));
    const panel = await screen.findByRole("tabpanel");
    const toggle = within(panel).getByRole("checkbox", { name: /download while reading/i });
    expect(toggle).not.toBeChecked();                         // INV-08: off by default

    await user.click(toggle);
    const write = calls.find((call) => call.method === "POST" && call.url === "/api/downloads/settings");
    expect(write?.body).toEqual({ auto_download: { enabled: true } });
  });

  it("turns the Source Recovered notice on, which is off until asked for", async () => {
    const calls = mockApi([...ALL, post("/api/notifications/settings", { source_recovered: true })]);
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />);
    await screen.findByRole("tablist", { name: /settings/i });

    await user.click(screen.getByRole("tab", { name: "Notifications" }));
    const panel = await screen.findByRole("tabpanel");
    const toggle = within(panel).getByRole("checkbox", { name: /starts working again/i });
    expect(toggle).not.toBeChecked();

    await user.click(toggle);
    expect(calls.find((call) => call.url === "/api/notifications/settings" && call.method === "POST")?.body)
      .toEqual({ source_recovered: true });
  });

  it("shows what the local diagnostics hold, and can clear them", async () => {
    // §43: operational records, kept locally and bounded. Nothing sends them anywhere.
    const calls = mockApi([...ALL, del("/api/diagnostics", { cleared: 3 })]);
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />);
    await screen.findByRole("tablist", { name: /settings/i });

    await user.click(screen.getByRole("tab", { name: "Advanced" }));
    const panel = await screen.findByRole("tabpanel");
    await user.click(within(panel).getByRole("button", { name: /advanced/i }));

    expect(await within(panel).findByText(/42 records/i)).toBeInTheDocument();
    expect(within(panel).getByText(/1\.1 MB/)).toBeInTheDocument();
    expect(within(panel).getByText(/7 days/i)).toBeInTheDocument();
    expect(within(panel).getByText(/never leave this machine/i)).toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: /clear the diagnostics/i }));
    expect(calls.some((call) => call.method === "DELETE" && call.url === "/api/diagnostics")).toBe(true);
  });
});
