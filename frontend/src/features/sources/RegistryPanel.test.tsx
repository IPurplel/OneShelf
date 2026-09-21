/**
 * Sources → Source Registry. The Registry is read against what is installed, so a fresh library
 * shows its eight official sources as Installed; a removed one comes back through the same review a file
 * gets; and nothing — not an update, not a reinstall — happens without that review.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RegistryPanel } from "./RegistryPanel";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

const card = (over: Record<string, unknown>) => ({
  id: "oneshelf.tapas", name: "Tapas", version: "1.0.0", trust_label: "official", signed: true,
  effective_trust: "official", api: "1.0", state: "installed", installed_version: "1.0.0",
  plugin_state: "active", channel: "bundled", installed_trust: "official", ...over,
});

const listing = (...plugins: Record<string, unknown>[]) => ({
  configured: true, location: "https://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/index.json",
  plugins,
});

const REVIEW = {
  id: "oneshelf.tapas", name: "Tapas", version: "1.0.0", publisher: "OneShelf", description: "Tapas comics.",
  capabilities: ["work", "catalog", "reader"],
  permissions: ["network:cdn:us-a.tapas.io", "network:domain:tapas.io"],
  added_permissions: ["network:cdn:us-a.tapas.io", "network:domain:tapas.io"],
  tests_passed: true, test_cases: 5, test_failures: [], effective_trust: "official", claimed_trust: "official",
  signed: true, sha256: "b".repeat(64), state: "available", installed_version: null, plugin_state: "uninstalled",
  channel: "bundled",
};

afterEach(() => vi.unstubAllGlobals());

const cardFor = async (name: string) => {
  const section = await screen.findByRole("region", { name: /^source registry$/i });
  const item = (await within(section).findAllByRole("listitem")).find((li) => within(li).queryByText(name));
  if (!item) throw new Error(`no card for ${name}`);
  return item;
};

describe("Source Registry", () => {
  it("shows an official source that is already installed as Installed, with nothing to press", async () => {
    mockApi([get("/api/registry", listing(card({})))]);
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);
    const tapas = await cardFor("Tapas");
    expect(within(tapas).getByText(/^installed$/i)).toBeInTheDocument();
    expect(within(tapas).getByText("Official")).toBeInTheDocument();
    expect(within(tapas).queryByRole("button")).toBeNull();
  });

  it("offers a removed source again, and installs it only after its review, bound to the reviewed bytes", async () => {
    const calls = mockApi([
      get("/api/registry", listing(card({ state: "available", installed_version: null, plugin_state: "uninstalled" }))),
      post("/api/registry/review-package", REVIEW),
      post("/api/registry/install", { plugin_id: "oneshelf.tapas", version: "1.0.0", state: "active",
                                      added_permissions: REVIEW.permissions, auth_available: false, steps: [] }),
    ]);
    const changed = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<RegistryPanel revision={0} onChanged={changed} />);

    await user.click(within(await cardFor("Tapas")).getByRole("button", { name: /^install$/i }));
    const review = await screen.findByRole("dialog", { name: /tapas/i });
    expect(within(review).getByText(/reach tapas\.io/i)).toBeInTheDocument();
    expect(within(review).getByText(/5 packaged tests passed/i)).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/registry/install")).toBe(false);

    await user.click(within(review).getByRole("button", { name: /install this source/i }));
    const install = calls.find((c) => c.url === "/api/registry/install");
    expect(install?.body).toEqual({ plugin_id: "oneshelf.tapas", version: "1.0.0",
                                    approved_permissions: REVIEW.permissions, sha256: REVIEW.sha256 });
    expect(await screen.findByText(/tapas 1\.0\.0 is installed/i)).toBeInTheDocument();
    expect(changed).toHaveBeenCalled();
  });

  it("offers a newer version as an update and marks what it newly asks for", async () => {
    mockApi([
      get("/api/registry", listing(card({ id: "oneshelf.hindawi", name: "Hindawi", version: "1.1.0",
                                          state: "update_available", installed_version: "1.0.0" }))),
      post("/api/registry/review-package", { ...REVIEW, id: "oneshelf.hindawi", name: "Hindawi", version: "1.1.0",
        permissions: ["network:domain:hindawi.org", "network:domain:www.hindawi.org"],
        added_permissions: ["network:domain:www.hindawi.org"], state: "update_available",
        installed_version: "1.0.0", plugin_state: "active" }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);

    const hindawi = await cardFor("Hindawi");
    expect(within(hindawi).getByText(/1\.0\.0 → 1\.1\.0/)).toBeInTheDocument();
    await user.click(within(hindawi).getByRole("button", { name: /^update$/i }));
    const review = await screen.findByRole("dialog", { name: /hindawi/i });
    const added = within(review).getByText(/reach www\.hindawi\.org/i).closest("li")!;
    expect(within(added).getByText(/^new$/i)).toBeInTheDocument();
    const kept = within(review).getByText(/reach hindawi\.org/i).closest("li")!;
    expect(within(kept).queryByText(/^new$/i)).toBeNull();
    expect(within(review).getByRole("button", { name: /update to 1\.1\.0/i })).toBeInTheDocument();
  });

  it("says a disabled source has an update, and that updating keeps it disabled", async () => {
    mockApi([
      get("/api/registry", listing(card({ version: "1.1.0", state: "update_available", plugin_state: "disabled" }))),
      post("/api/registry/review-package", { ...REVIEW, version: "1.1.0", added_permissions: [],
                                             state: "update_available", installed_version: "1.0.0",
                                             plugin_state: "disabled" }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);
    const tapas = await cardFor("Tapas");
    expect(within(tapas).getByText(/disabled · update available/i)).toBeInTheDocument();
    await user.click(within(tapas).getByRole("button", { name: /^update$/i }));
    expect(await screen.findByText(/stays disabled/i)).toBeInTheDocument();
  });

  it("asks for review of an update that is already waiting", async () => {
    mockApi([get("/api/registry", listing(card({ version: "1.1.0", state: "pending_review" })))]);
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);
    const tapas = await cardFor("Tapas");
    expect(within(tapas).getByRole("button", { name: /review update/i })).toBeInTheDocument();
  });

  it("never offers an older Registry version over a newer installed one", async () => {
    mockApi([get("/api/registry", listing(card({ state: "installed_newer", installed_version: "2.0.0" })))]);
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);
    const tapas = await cardFor("Tapas");
    expect(within(tapas).getByText(/installed version 2\.0\.0 is newer/i)).toBeInTheDocument();
    expect(within(tapas).queryByRole("button")).toBeNull();
  });

  it("labels an adapter this OneShelf cannot run instead of offering it", async () => {
    mockApi([get("/api/registry", listing(card({ state: "incompatible", api: "1.9", installed_version: null })))]);
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);
    const tapas = await cardFor("Tapas");
    expect(within(tapas).getByText(/requires a newer oneshelf/i)).toBeInTheDocument();
    expect(within(tapas).queryByRole("button")).toBeNull();
  });

  it("does not call an unsigned claim Official", async () => {
    mockApi([get("/api/registry", listing(card({ signed: false, effective_trust: "community" })))]);
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);
    const tapas = await cardFor("Tapas");
    expect(within(tapas).queryByText("Official")).toBeNull();
    expect(within(tapas).getByText(/not verified/i)).toBeInTheDocument();
  });

  it("is not called Official when it holds every trust level", async () => {
    mockApi([get("/api/registry", listing(card({})))]);
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);
    expect(await screen.findByRole("heading", { name: /^source registry$/i })).toBeInTheDocument();
    expect(screen.queryByText(/official source registry/i)).toBeNull();
  });

  it("shows each entry's own trust level, from its signature", async () => {
    mockApi([get("/api/registry", listing(
      card({}),
      card({ id: "example.verified", name: "Verified Books", trust_label: "verified_community",
             effective_trust: "verified_community", state: "available", installed_version: null }),
      card({ id: "example.claims", name: "Claims Books", trust_label: "verified_community", signed: false,
             effective_trust: "community", state: "available", installed_version: null }),
      card({ id: "example.books", name: "Community Books", trust_label: "community", signed: false,
             effective_trust: "community", state: "available", installed_version: null }),
    ))]);
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);
    expect(within(await cardFor("Tapas")).getByText("Official")).toBeInTheDocument();
    expect(within(await cardFor("Verified Books")).getByText("Verified Community")).toBeInTheDocument();
    expect(within(await cardFor("Claims Books")).getByText(/says verified community · not verified/i)).toBeInTheDocument();
    const community = await cardFor("Community Books");
    expect(within(community).getByText("Community")).toBeInTheDocument();
    expect(within(community).getByRole("button", { name: /^install$/i })).toBeInTheDocument();
  });

  it("will not install from a review whose packaged tests failed", async () => {
    mockApi([
      get("/api/registry", listing(card({ state: "available", installed_version: null }))),
      post("/api/registry/review-package", { ...REVIEW, tests_passed: false, test_failures: ["work: 0 items"] }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);
    await user.click(within(await cardFor("Tapas")).getByRole("button", { name: /^install$/i }));
    expect(await screen.findByText("work: 0 items")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /install this source/i })).toBeNull();
  });

  it("says why a review was refused", async () => {
    mockApi([
      get("/api/registry", listing(card({ state: "available", installed_version: null }))),
      post("/api/registry/review-package",
           { error: { code: "REVIEW_REJECTED", message: "package hash does not match the registry entry" } }, 422),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);
    await user.click(within(await cardFor("Tapas")).getByRole("button", { name: /^install$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("package hash does not match");
  });

  it("stays calm when the Registry cannot be reached, and can try again", async () => {
    const calls = mockApi([get("/api/registry",
      { error: { code: "REGISTRY_UNAVAILABLE", message: "registry unavailable (ConnectError)" } }, 502)]);
    const user = userEvent.setup();
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);
    expect(await screen.findByText(/installed sources keep working/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(calls.some((c) => c.url.startsWith("/api/registry?") && c.url.includes("refresh=true"))).toBe(true);
  });

  it("says plainly when no Registry is configured", async () => {
    mockApi([get("/api/registry", { configured: false, plugins: [] })]);
    renderWithProviders(<RegistryPanel revision={0} onChanged={() => {}} />);
    expect(await screen.findByText(/no source registry is configured/i)).toBeInTheDocument();
  });
});
