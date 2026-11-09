/** Your own shelves (asked for 2026-11-10): "Novels", "Manga", "Summer", drawn as shelves of covers. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import { MyShelves } from "./MyShelves";
import { CollectionScreen } from "./CollectionScreen";
import { ShelvesPicker } from "./ShelvesPicker";
import { renderWithProviders } from "@/test/render";
import { del, get, mockApi, post } from "@/test/http";

const SUMMER = { id: "c1", name: "Summer", work_count: 2, is_smart: false, filter_json: null, covers: [null, null],
  works: [{ work_id: "w1", title: "The Stranger", content_type: "novel", cover_url: null },
          { work_id: "w2", title: "One Piece", content_type: "manga", cover_url: null }] };

afterEach(() => vi.unstubAllGlobals());

describe("My shelves", () => {
  it("shows each of your shelves with its works and a way to open it", async () => {
    mockApi([get("/api/collections", { collections: [SUMMER] })]);
    renderWithProviders(<MyShelves />);
    const shelf = await screen.findByRole("region", { name: /summer/i });
    expect(within(shelf).getByText("The Stranger")).toBeInTheDocument();
    expect(within(shelf).getByRole("link", { name: /view all/i })).toHaveAttribute("href", "/shelves/c1");
  });

  it("makes a new shelf by name", async () => {
    const calls = mockApi([get("/api/collections", { collections: [] }),
                           post("/api/collections", { id: "c2", name: "Novels" })]);
    const user = userEvent.setup();
    renderWithProviders(<MyShelves />);
    await user.click(await screen.findByRole("button", { name: /new shelf/i }));
    await user.type(screen.getByRole("textbox", { name: /shelf name/i }), "Novels{Enter}");
    expect(calls.find((c) => c.url === "/api/collections" && c.method === "POST")?.body).toEqual({ name: "Novels" });
  });
});

describe("A shelf of your own", () => {
  const render = () => renderWithProviders(
    <Routes><Route path="/shelves/:collectionId" element={<CollectionScreen />} /></Routes>,
    { route: "/shelves/c1" });

  it("lists its works, and takes one off without touching the library", async () => {
    const calls = mockApi([get("/api/collections/c1", { id: "c1", name: "Summer", works: SUMMER.works }),
                           del("/api/collections/c1/works/w1", { collection_id: "c1", work_id: "w1" })]);
    const user = userEvent.setup();
    render();
    expect(await screen.findByRole("heading", { level: 1, name: "Summer" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /take “the stranger” off this shelf/i }));
    expect(calls.some((c) => c.url === "/api/collections/c1/works/w1" && c.method === "DELETE")).toBe(true);
  });

  it("is renamed in place", async () => {
    const calls = mockApi([get("/api/collections/c1", { id: "c1", name: "Summer", works: [] }),
      { match: (url: string, init?: RequestInit) => url === "/api/collections/c1" && init?.method === "PATCH",
        payload: { id: "c1", name: "Summer 2026" } }]);
    const user = userEvent.setup();
    render();
    await user.click(await screen.findByRole("button", { name: /rename/i }));
    const field = screen.getByRole("textbox", { name: /shelf name/i });
    await user.clear(field);
    await user.type(field, "Summer 2026{Enter}");
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "Summer 2026" });
  });
});

describe("Putting a work on your shelves", () => {
  it("ticks the shelves that hold it and adds or removes it on a tap", async () => {
    const calls = mockApi([
      get("/api/collections", { collections: [SUMMER, { ...SUMMER, id: "c2", name: "Novels", works: [] }] }),
      get("/api/works/w1/collections", { collection_ids: ["c1"] }),
      post("/api/collections/c2/works/w1", { collection_id: "c2", work_id: "w1" }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ShelvesPicker workId="w1" title="The Stranger" onClose={() => {}} />);
    expect(await screen.findByRole("checkbox", { name: "Summer" })).toBeChecked();
    const novels = screen.getByRole("checkbox", { name: "Novels" });
    expect(novels).not.toBeChecked();
    await user.click(novels);
    expect(calls.some((c) => c.url === "/api/collections/c2/works/w1" && c.method === "POST")).toBe(true);
    expect(novels).toBeChecked();
  });
});
