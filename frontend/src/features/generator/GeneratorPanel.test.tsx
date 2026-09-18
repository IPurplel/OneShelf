/** Master §12, §32.14: the generator proposes, the developer reviews, and nothing installs by itself. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GeneratorPanel } from "./GeneratorPanel";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

const DRAFT = {
  id: "d1", state: "draft", start_url: "https://example.org", package_path: null, bundle_path: null,
  manifest: { id: "generated.example-org", name: "Example", version: "0.1.0",
              capabilities: ["search", "listing"], network: { domains: ["example.org"], cdn_domains: [] } },
  source: { id: "generated.example-org" },
  recipes: {
    search: { request: { url_template: "{base_url}/search?q={query}" }, response: { format: "html" },
              extract: { items: { css: "li.result" },
                         fields: { listing_key: { css: "h3 a", transforms: ["normalize_url"] },
                                   title: { css: "h3 a", required: true } } } },
  },
  tests: { cases: 2 },
  confidence: { search: "confirmed", listing: "probable" },
  unsupported: { reader: "the pages are drawn by script after loading" },
  notes: ["robots.txt allows /search"],
  fetches: ["https://example.org/search?q=test"],
  permissions: ["network:domain:example.org"],
  rejected_domains: ["tracker.example.net"],
};

const SOURCES = { sources: [{ id: "oneshelf.example", name: "Example", state: "active", version: "1.0.0",
                              trust_label: "community", channel: "upload", capabilities: ["search"],
                              auth_available: false, session_state: "none" }] };

const draft = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.type(screen.getByRole("textbox", { name: /address of a page/i }), "https://example.org");
  await user.type(screen.getByRole("textbox", { name: /name/i }), "Example");
  await user.click(screen.getByRole("button", { name: /look at this site/i }));
  return screen.findByText("generated.example-org");
};

afterEach(() => vi.unstubAllGlobals());

describe("Adapter generator", () => {
  it("reports what it worked out and what it could not, in the Master's own states", async () => {
    mockApi([get("/api/sources", SOURCES), get("/api/generator/drafts", { drafts: [] }),
             post("/api/generator/drafts", DRAFT)]);
    const user = userEvent.setup();
    renderWithProviders(<GeneratorPanel />);
    await draft(user);

    expect(await screen.findByText(/confirmed/i)).toBeInTheDocument();
    expect(screen.getByText(/probable/i)).toBeInTheDocument();
    expect(screen.getByText(/the pages are drawn by script after loading/i)).toBeInTheDocument();
    expect(screen.getByText(/reach example\.org/i)).toBeInTheDocument();
    expect(screen.getByText(/tracker\.example\.net/)).toBeInTheDocument();
  });

  it("shows every field and the selector behind it", async () => {
    mockApi([get("/api/sources", SOURCES), get("/api/generator/drafts", { drafts: [] }),
             post("/api/generator/drafts", DRAFT)]);
    const user = userEvent.setup();
    renderWithProviders(<GeneratorPanel />);
    await draft(user);

    await user.click(await screen.findByRole("button", { name: /inspect the recipes/i }));
    const inspector = await screen.findByRole("region", { name: /recipe inspector/i });
    expect(within(inspector).getByText("title")).toBeInTheDocument();
    expect(within(inspector).getAllByText("h3 a").length).toBeGreaterThan(0);
    expect(within(inspector).getByText(/normalize_url/)).toBeInTheDocument();
  });

  it("will not offer to install until the package's own tests pass", async () => {
    mockApi([get("/api/sources", SOURCES), get("/api/generator/drafts", { drafts: [] }),
             post("/api/generator/drafts/d1/generate", { path: "/work/d1.osp", installed: false }),
             post("/api/generator/drafts/d1/test", { passed: true, cases: 2, failures: [] }),
             post("/api/generator/drafts", DRAFT)]);
    const user = userEvent.setup();
    renderWithProviders(<GeneratorPanel />);
    await draft(user);

    expect(screen.queryByRole("button", { name: /install this source/i })).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /build the package/i }));
    await user.click(await screen.findByRole("button", { name: /run the packaged tests/i }));

    expect(await screen.findByText(/2 packaged tests passed/i)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /install this source/i })).toBeInTheDocument();
  });

  it("installs the draft with exactly the permissions it showed", async () => {
    const calls = mockApi([get("/api/sources", SOURCES), get("/api/generator/drafts", { drafts: [] }),
                           post("/api/generator/drafts/d1/generate", { path: "/work/d1.osp", installed: false }),
                           post("/api/generator/drafts/d1/test", { passed: true, cases: 2, failures: [] }),
                           post("/api/generator/drafts/d1/install", { plugin_id: "generated.example-org",
                                                                      version: "0.1.0", state: "active" }),
                           post("/api/generator/drafts", DRAFT)]);
    const user = userEvent.setup();
    renderWithProviders(<GeneratorPanel />);
    await draft(user);
    await user.click(await screen.findByRole("button", { name: /build the package/i }));
    await user.click(await screen.findByRole("button", { name: /run the packaged tests/i }));
    await user.click(await screen.findByRole("button", { name: /install this source/i }));

    const install = calls.find((c) => c.url === "/api/generator/drafts/d1/install");
    expect(install?.body).toEqual({ approved_permissions: ["network:domain:example.org"] });
  });

  it("prepares a submission bundle without sending it anywhere", async () => {
    mockApi([get("/api/sources", SOURCES), get("/api/generator/drafts", { drafts: [] }),
             post("/api/generator/drafts/d1/submission", { path: "/work/d1-submission.zip", published: false }),
             post("/api/generator/drafts", DRAFT)]);
    const user = userEvent.setup();
    renderWithProviders(<GeneratorPanel />);
    await draft(user);

    await user.click(await screen.findByRole("button", { name: /prepare a submission bundle/i }));
    expect(await screen.findByText("/work/d1-submission.zip")).toBeInTheDocument();
    expect(screen.getByText(/nothing was sent anywhere/i)).toBeInTheDocument();
  });

  it("diagnoses an installed source and shows each selector change before activating a repair", async () => {
    const calls = mockApi([
      get("/api/sources", SOURCES), get("/api/generator/drafts", { drafts: [] }),
      post("/api/generator/repair/oneshelf.example/diagnose",
           { plugin_id: "oneshelf.example", checked: ["search", "listing"], broken: ["search"],
             details: { search: "no items matched li.result" }, healthy: false }),
      post("/api/generator/repair/oneshelf.example",
           { plugin_id: "oneshelf.example", version: "1.0.1", path: "/work/repair.osp", validated: true,
             installed: false, changes: [{ capability: "search", field_name: "title",
                                           before: "h3 a", after: "h2 > a.title" }], notes: [] }),
      post("/api/generator/repair/oneshelf.example/activate",
           { plugin_id: "oneshelf.example", version: "1.0.1", state: "active" }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<GeneratorPanel />);

    await user.click(await screen.findByRole("button", { name: /check this source/i }));
    expect(await screen.findByText(/no items matched li\.result/)).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: /propose a repair/i }));
    expect(await screen.findByText("h2 > a.title")).toBeInTheDocument();
    expect(screen.getByText("h3 a")).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: /activate this repair/i }));
    const activate = calls.find((c) => c.url === "/api/generator/repair/oneshelf.example/activate");
    expect(activate?.body).toEqual({ approved_permissions: [], path: "/work/repair.osp" });
  });
});
