/** Master §32.14, §45: a readable document, categories beside the panel, progressive disclosure. */
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLocation, useNavigate } from "react-router-dom";
import { SettingsScreen } from "./SettingsScreen";
import { renderApp, renderWithProviders } from "@/test/render";
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

function HistoryControls() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output aria-label="Location">{location.pathname}</output>
    <button onClick={() => void navigate(-1)}>Back</button>
    <button onClick={() => void navigate(1)}>Forward</button><SettingsScreen /></>;
}

describe("Settings route", () => {
  it.each([["/settings/storage", "Storage"], ["/settings", "General"], ["/settings/invalid", "General"]])(
    "opens %s as %s", async (route, name) => {
      mockApi([get("/api/storage", STORAGE)]);
      renderApp({ route });
      expect(await screen.findByRole("tabpanel", { name })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true");
    });

  it("writes category URLs and follows Back and Forward", async () => {
    mockApi([get("/api/storage", STORAGE)]);
    const user = userEvent.setup();
    renderWithProviders(<HistoryControls />, { route: "/settings" });
    await user.click(screen.getByRole("tab", { name: "Storage" }));
    expect(screen.getByLabelText("Location")).toHaveTextContent("/settings/storage");
    await user.click(screen.getByRole("tab", { name: "General" }));
    expect(screen.getByRole("tabpanel", { name: "General" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("tabpanel", { name: "Storage" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Forward" }));
    expect(screen.getByRole("tabpanel", { name: "General" })).toBeInTheDocument();
  });
});


describe("Settings failure recovery", () => {
  it.each(["", "0", "21", "2.5"])("does not save invalid read-ahead value %s", async value => {
    const enabled = { ...DOWNLOADS, auto_download: { ...DOWNLOADS.auto_download,
      enabled: true, mode: "read_ahead" } };
    const calls = mockApi([get("/api/downloads/settings", enabled)]);
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />, { route: "/settings/downloads" });
    const input = await screen.findByRole("spinbutton", { name: /how many units ahead/i });
    await user.clear(input);
    if (value) await user.type(input, value);
    await user.tab();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(calls.filter(call => call.method === "POST")).toHaveLength(0);
  });

  async function reader() {
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />, { route: "/settings/reader" });
    await user.click(screen.getByRole("button", { name: /show advanced/i }));
    return { user, threshold: await screen.findByRole("spinbutton", { name: /count a unit/i }) };
  }

  it.each(["101", "49", "", "97.5"])("does not save invalid completion percentage %s", async value => {
    const calls = mockApi([get("/api/reader/settings", READER), post("/api/reader/settings", READER)]);
    const { user, threshold } = await reader();
    await user.clear(threshold);
    if (value) await user.type(threshold, value);
    await user.tab();
    expect(threshold).toHaveAttribute("aria-invalid", "true");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(calls.filter(c => c.method === "POST")).toHaveLength(0);
  });

  it("keeps a rejected draft visibly unsaved and can retry it", async () => {
    let reject = true;
    let setting = READER;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        if (reject) return Response.json({ error: { message: "Disk unavailable" } }, { status: 503 });
        setting = { ...READER, auto_mark_read_threshold: .9 };
      }
      return Response.json(setting);
    }));
    const { user, threshold } = await reader();
    await user.clear(threshold); await user.type(threshold, "90"); await user.tab();
    expect(await screen.findByRole("alert")).toHaveTextContent(/not saved.*Disk unavailable/i);
    expect(threshold).toHaveValue(90);
    reject = false;
    await user.click(screen.getByRole("button", { name: /^try again$/i }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(threshold).toHaveValue(90);
  });

  it("blocks overlapping reader writes while a save is pending", async () => {
    let finish!: (response: Response) => void;
    const fetcher = vi.fn((_url: string, init?: RequestInit) => init?.method === "POST"
      ? new Promise<Response>(resolve => { finish = resolve; }) : Promise.resolve(Response.json(READER)));
    vi.stubGlobal("fetch", fetcher);
    const { user, threshold } = await reader();
    await user.clear(threshold); await user.type(threshold, "90"); await user.tab();
    expect(screen.getByRole("spinbutton", { name: /pages ahead/i })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /remember/i })).toBeDisabled();
    await act(async () => finish(Response.json(READER)));
  });

  it("offers a retry after download settings fail to load", async () => {
    let failed = true;
    vi.stubGlobal("fetch", vi.fn(async () => failed
      ? Response.json({ error: { message: "Service unavailable" } }, { status: 503 })
      : Response.json(DOWNLOADS)));
    const user = userEvent.setup();
    renderWithProviders(<SettingsScreen />, { route: "/settings/downloads" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    failed = false;
    await user.click(screen.getByRole("button", { name: /^try again$/i }));
    expect(await screen.findByRole("checkbox", { name: /download while/i })).toBeInTheDocument();
  });
});
