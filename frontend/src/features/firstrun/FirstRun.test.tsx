/** Master §29, §32.17: a short welcome that never blocks the library. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FirstRunScreen } from "./FirstRunScreen";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

const PENDING = {
  state: "pending", access_mode: null,
  steps: [{ id: "welcome", optional: false }, { id: "storage", optional: false },
          { id: "access_mode", optional: false }, { id: "remote", optional: true },
          { id: "sources", optional: true }, { id: "finish", optional: false }],
  storage: [], remote: { canonical_hostname: null, passkey_registered: false },
  network: { trusted_networks: [], trusted_proxies: [], gateway_warning: null },
  sources_installed: 0, completed_at: null,
};

afterEach(() => vi.unstubAllGlobals());

describe("First run", () => {
  it("welcomes with the Master's words", async () => {
    mockApi([get("/api/first-run", PENDING)]);
    renderWithProviders(<FirstRunScreen />);
    expect(await screen.findByRole("heading", { name: /welcome to oneshelf/i })).toBeInTheDocument();
    expect(screen.getByText(/your stories, one library/i)).toBeInTheDocument();
  });

  it("asks for a storage location, then the access mode", async () => {
    const calls = mockApi([
      get("/api/first-run", PENDING),
      post("/api/first-run/storage", { id: "r1", name: "Library", path: "/library", default: true }),
      post("/api/first-run/access-mode", { ...PENDING, access_mode: "local" }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<FirstRunScreen />);
    await screen.findByRole("heading", { name: /welcome to oneshelf/i });

    await user.click(screen.getByRole("button", { name: /continue/i }));
    await user.type(await screen.findByRole("textbox", { name: /where should oneshelf keep/i }), "/library");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(calls.some((c) => c.url === "/api/first-run/storage")).toBe(true);
    const modes = await screen.findByRole("radiogroup", { name: /who can reach/i });
    expect(within(modes).getAllByRole("radio").map((r) => r.getAttribute("value")))
      .toEqual(["local", "lan", "remote"]);
  });

  it("asks for a hostname only when remote is chosen", async () => {
    mockApi([get("/api/first-run", { ...PENDING, access_mode: "lan", storage: [{ id: "r1", name: "Library",
                                                                                 path: "/library", default: true }] })]);
    const user = userEvent.setup();
    renderWithProviders(<FirstRunScreen initialStep="access_mode" />);
    await screen.findByRole("radiogroup", { name: /who can reach/i });

    expect(screen.queryByRole("textbox", { name: /hostname/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /anywhere/i }));
    expect(await screen.findByRole("textbox", { name: /hostname/i })).toBeInTheDocument();
  });

  it("lets someone reach their library without finishing the tour", async () => {
    mockApi([get("/api/first-run", PENDING)]);
    renderWithProviders(<FirstRunScreen />);
    await screen.findByRole("heading", { name: /welcome to oneshelf/i });
    expect(screen.getByRole("link", { name: /skip for now|go to my library/i })).toHaveAttribute("href", "/");
  });
});
