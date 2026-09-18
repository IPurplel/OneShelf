/** Master §31, §32.3–32.5: Home is adaptive, library-first, and never invents content. */
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HomeScreen } from "./HomeScreen";
import { renderWithProviders } from "@/test/render";
import type { HomeResponse } from "@/api/types";

const EMPTY: HomeResponse = { hero: null, continue_reading: [], trending: [], latest: [], recently_added: [] };

function respondWith(payload: HomeResponse) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(payload), {
    status: 200, headers: { "Content-Type": "application/json" },
  })));
}

beforeEach(() => respondWith(EMPTY));
afterEach(() => vi.unstubAllGlobals());

describe("Home", () => {
  it("welcomes a new library without inventing books or statistics", async () => {
    renderWithProviders(<HomeScreen />);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(/welcome/i);
    expect(screen.queryByRole("region", { name: /trending/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /latest releases/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /continue reading/i })).not.toBeInTheDocument();
    expect(screen.getByText(/add your first/i)).toBeInTheDocument();
    expect(screen.queryByText(/\d+ (works|books|readers)/i)).not.toBeInTheDocument();
  });

  it("shows a hero drawn from what you were reading, with its reason", async () => {
    respondWith({
      ...EMPTY,
      hero: { reason: "continue_reading", title: "The Irregular Chronicle", work_id: "w1", cover_url: null },
      continue_reading: [{ work_id: "w1", title: "The Irregular Chronicle", cover_url: null, fraction: 0.42 }],
    });
    renderWithProviders(<HomeScreen />);
    const hero = await screen.findByRole("region", { name: "The Irregular Chronicle" });
    expect(within(hero).getByRole("heading", { name: "The Irregular Chronicle" })).toBeInTheDocument();
    expect(within(hero).getByText(/continue reading/i, { selector: ".hero__reason" })).toBeInTheDocument();
    expect(within(hero).getByRole("link", { name: /continue reading/i })).toHaveAttribute("href", "/works/w1");
    expect(within(hero).getByText("42%")).toBeInTheDocument();
  });

  it("hides discovery sections that no source supplied", async () => {
    respondWith({ ...EMPTY, recently_added: [{ work_id: "w2", title: "The Manual", cover_url: null, fraction: null }] });
    renderWithProviders(<HomeScreen />);
    const added = await screen.findByRole("region", { name: /recently added/i });
    expect(within(added).getByRole("link", { name: /the manual/i })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /trending/i })).not.toBeInTheDocument();
  });

  it("shows trending only when a source actually provided it, with honest availability", async () => {
    respondWith({
      ...EMPTY,
      trending: [{
        work_id: "w3", title: "حكاية القمر", content_type: "manga", soft: false,
        availability: { ar: 2 },
        provenance: [
          { source_id: "s1", listing_key: "k1", language: "ar", title: "حكاية القمر", url: null },
          { source_id: "s2", listing_key: "k2", language: "ar", title: "حكاية القمر", url: null },
        ],
      }],
    });
    renderWithProviders(<HomeScreen />);
    const trending = await screen.findByRole("region", { name: /trending/i });
    expect(within(trending).getByText("حكاية القمر")).toBeInTheDocument();
    expect(within(trending).getByText(/2 sources/i)).toBeInTheDocument();
  });

  it("says so plainly when the library cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 503 })));
    renderWithProviders(<HomeScreen />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not responding|could not/i);
  });
});
