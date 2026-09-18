/** Master §28, §32.14: remote access set up from a trusted device, in plain words. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RemotePanel } from "./RemotePanel";
import { renderWithProviders } from "@/test/render";
import { del, get, mockApi, post } from "@/test/http";

const UNSET = {
  canonical_hostname: null, remote_enabled: false, passkeys: [], sessions: [],
  recovery: { configured: false, created_at: null, last_used_at: null },
  access: "lan", network: { trusted_networks: ["192.168.1.0/24"], trusted_proxies: [], gateway_warning: null },
  session_lifetimes: ["7d", "30d", "90d", "1y", "manual"],
};

const READY = {
  ...UNSET,
  canonical_hostname: "oneshelf.example.net",
  remote_enabled: true,
  passkeys: [{ credential_id: "c1", label: "Phone", created_at: "2026-09-18T09:00:00+00:00",
               last_used_at: null, backed_up: true }],
  sessions: [{ id: "s1", label: "Firefox on Linux", created_at: "2026-09-18T09:00:00+00:00",
               last_active_at: "2026-09-18T10:00:00+00:00", expires_at: "2026-10-18T09:00:00+00:00",
               current: false }],
  recovery: { configured: true, created_at: "2026-09-18T09:00:00+00:00", last_used_at: null },
};

afterEach(() => vi.unstubAllGlobals());

describe("Remote access", () => {
  it("says it is not set up, and what that means", async () => {
    mockApi([get("/api/auth/state", UNSET)]);
    renderWithProviders(<RemotePanel />);
    expect(await screen.findByText(/not set up/i)).toBeInTheDocument();
    expect(screen.getByText(/this device and your trusted network/i)).toBeInTheDocument();
  });

  it("takes the canonical hostname before offering a passkey", async () => {
    const calls = mockApi([get("/api/auth/state", UNSET),
                           post("/api/auth/hostname", { hostname: "oneshelf.example.net" })]);
    const user = userEvent.setup();
    renderWithProviders(<RemotePanel />);
    await screen.findByText(/not set up/i);

    expect(screen.queryByRole("button", { name: /add a passkey/i })).not.toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: /hostname/i }), "oneshelf.example.net");
    await user.click(screen.getByRole("button", { name: /save/i }));
    expect(calls.some((c) => c.url === "/api/auth/hostname")).toBe(true);
  });

  it("shows passkeys, sessions and the recovery code state once remote is on", async () => {
    mockApi([get("/api/auth/state", READY)]);
    renderWithProviders(<RemotePanel />);

    expect(await screen.findByText("Phone")).toBeInTheDocument();
    expect(screen.getByText("Firefox on Linux")).toBeInTheDocument();
    expect(screen.getByText(/recovery code is set/i)).toBeInTheDocument();
    expect(screen.queryByText(/[A-Z2-9]{5}-[A-Z2-9]{5}/)).not.toBeInTheDocument();   // never shown again
  });

  it("revokes a session and removes a passkey through the library", async () => {
    const calls = mockApi([get("/api/auth/state", READY), del("/api/auth/sessions/s1", { revoked: true }),
                           del("/api/auth/passkeys/c1", { removed: true })]);
    const user = userEvent.setup();
    renderWithProviders(<RemotePanel />);
    await screen.findByText("Phone");

    await user.click(screen.getByRole("button", { name: /sign out this device/i }));
    await user.click(screen.getByRole("button", { name: /remove this passkey/i }));
    expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/auth/sessions/s1")).toBe(true);
    expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/auth/passkeys/c1")).toBe(true);
  });

  it("shows a new recovery code once, and says the old one stopped working", async () => {
    mockApi([get("/api/auth/state", READY),
             post("/api/auth/recovery/regenerate", { recovery_code: "ABCDE-FGHJK-LMNPQ-RSTUV-WXYZ2" })]);
    const user = userEvent.setup();
    renderWithProviders(<RemotePanel />);
    await screen.findByText("Phone");

    await user.click(screen.getByRole("button", { name: /new recovery code/i }));
    expect(await screen.findByText("ABCDE-FGHJK-LMNPQ-RSTUV-WXYZ2")).toBeInTheDocument();
    expect(screen.getByText(/only time you will see it/i)).toBeInTheDocument();
    expect(screen.getByText(/previous code no longer works/i)).toBeInTheDocument();
  });

  it("explains exactly what LAN recovery resets before doing it", async () => {
    const calls = mockApi([get("/api/auth/state", READY),
                           post("/api/auth/lan-recovery", { passkeys_removed: 1, sessions_revoked: 1,
                                                            message: "This resets remote Web UI authentication only." })]);
    const user = userEvent.setup();
    renderWithProviders(<RemotePanel />);
    await screen.findByText("Phone");

    await user.click(screen.getByRole("button", { name: /reset remote access/i }));
    const dialog = await screen.findByRole("dialog", { name: /reset remote access/i });
    expect(dialog).toHaveTextContent(/every passkey is removed/i);
    expect(dialog).toHaveTextContent(/library, shelf, reading progress.*not affected/i);

    await user.click(within(dialog).getByRole("button", { name: /^reset remote access$/i }));
    expect(calls.some((c) => c.url === "/api/auth/lan-recovery")).toBe(true);
  });
});
