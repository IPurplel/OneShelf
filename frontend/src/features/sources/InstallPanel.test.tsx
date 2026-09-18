/** Master §10, §11, §32.12: nothing installs without a review the reader can actually understand. */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InstallPanel } from "./InstallPanel";
import { renderWithProviders } from "@/test/render";
import { mockApi, post } from "@/test/http";

const REVIEW = {
  upload_id: "abcdef123456", id: "oneshelf.example", name: "Example Library", version: "1.2.0",
  description: "A small public-domain library.", publisher: "Example", sha256: "a".repeat(64),
  capabilities: ["search", "listing", "download"], browser_capabilities: [],
  permissions: ["browser:login", "network:domain:example.org", "session:optional:download"], auth_available: true,
  tests: { passed: true, cases: 4, failures: [] },
};

const osp = () => new File([new Uint8Array([80, 75, 3, 4])], "example.osp", { type: "application/zip" });

afterEach(() => vi.unstubAllGlobals());

describe("Installing a source", () => {
  it("reviews the package, and installs nothing until asked", async () => {
    const calls = mockApi([post("/api/sources/uploads", REVIEW)]);
    const user = userEvent.setup();
    renderWithProviders(<InstallPanel onInstalled={() => {}} />);

    await user.upload(screen.getByLabelText(/choose an \.osp package/i), osp());

    expect(await screen.findByText("Example Library")).toBeInTheDocument();
    expect(screen.getByText(/1\.2\.0/)).toBeInTheDocument();
    expect(screen.getByText(/reach example\.org/i)).toBeInTheDocument();          // permissions in plain words
    expect(screen.getByText(/open a browser window so you can sign in/i)).toBeInTheDocument();
    expect(screen.getByText(/4 packaged tests passed/i)).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/sources/install")).toBe(false);
  });

  it("will not install a package whose own tests failed", async () => {
    mockApi([post("/api/sources/uploads",
                  { ...REVIEW, tests: { passed: false, cases: 4, failures: ["listing: 0 items"] } })]);
    const user = userEvent.setup();
    renderWithProviders(<InstallPanel onInstalled={() => {}} />);

    await user.upload(screen.getByLabelText(/choose an \.osp package/i), osp());

    expect(await screen.findByText(/listing: 0 items/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /install this source/i })).not.toBeInTheDocument();
  });

  it("installs with exactly the permissions that were shown", async () => {
    const calls = mockApi([post("/api/sources/uploads", REVIEW),
                           post("/api/sources/install", { plugin_id: "oneshelf.example", version: "1.2.0",
                                                          state: "active", added_permissions: REVIEW.permissions,
                                                          auth_available: true, steps: [] })]);
    const user = userEvent.setup();
    renderWithProviders(<InstallPanel onInstalled={() => {}} />);

    await user.upload(screen.getByLabelText(/choose an \.osp package/i), osp());
    await user.click(await screen.findByRole("button", { name: /install this source/i }));

    const install = calls.find((c) => c.url === "/api/sources/install");
    expect(install?.body).toEqual({ upload_id: "abcdef123456", approved_permissions: REVIEW.permissions });
    expect(await screen.findByText(/example library is installed/i)).toBeInTheDocument();
  });

  it("says why a package it cannot read was rejected", async () => {
    mockApi([post("/api/sources/uploads",
                  { error: { code: "INVALID_PACKAGE", message: "manifest.yaml is missing." } }, 422)]);
    const user = userEvent.setup();
    renderWithProviders(<InstallPanel onInstalled={() => {}} />);

    await user.upload(screen.getByLabelText(/choose an \.osp package/i), osp());

    expect(await screen.findByRole("alert")).toHaveTextContent("manifest.yaml is missing.");
  });
});
