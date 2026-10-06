/** Master §24, §37, §32.14: storage locations and the import flow, on operational paper. */
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StoragePanel } from "./StoragePanel";
import { ImportPanel } from "./ImportPanel";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

const ROOTS = {
  roots: [
    { id: "r1", name: "Library", path: "/library", is_default: true, available: true, reason: null,
      total: 500e9, free: 120e9, reserve: 5e9, state: "ok" },
    { id: "r2", name: "Archive drive", path: "/mnt/archive", is_default: false, available: false,
      reason: "not mounted" },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe("Storage", () => {
  it("keeps a failed Add dialog open with its entered values", async () => {
    mockApi([get("/api/storage", ROOTS),
      post("/api/storage/roots", { error: { message: "Location unavailable" } }, 503)]);
    const user = userEvent.setup();
    renderWithProviders(<StoragePanel />);
    await user.click(await screen.findByRole("button", { name: /add a location/i }));
    const dialog = screen.getByRole("dialog", { name: /add a storage location/i });
    await user.type(within(dialog).getByRole("textbox", { name: /folder/i }), "/books");
    await user.type(within(dialog).getByRole("textbox", { name: /name/i }), "Books");
    await user.click(within(dialog).getByRole("button", { name: /^add$/i }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Location unavailable");
    expect(within(dialog).getByRole("textbox", { name: /folder/i })).toHaveValue("/books");
  });
  it("shows each location with its space, and names an unavailable one without alarm", async () => {
    mockApi([get("/api/storage", ROOTS)]);
    renderWithProviders(<StoragePanel />);

    const rows = await screen.findAllByRole("listitem");
    expect(within(rows[0]!).getByText(/free of/i)).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/default/i)).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/unavailable/i)).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/not mounted/i)).toBeInTheDocument();
    expect(within(rows[1]!).queryByText(/missing|lost|deleted/i)).not.toBeInTheDocument();
  });

  it("adds a location and rescans when asked", async () => {
    const calls = mockApi([
      get("/api/storage", ROOTS),
      post("/api/storage/roots", { id: "r3", name: "Books", path: "/books" }),
      post("/api/storage/scan", { checked: 12, missing: 0, recovered: 0, corrupt: 0 }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<StoragePanel />);
    await screen.findAllByRole("listitem");

    await user.click(screen.getByRole("button", { name: /add a location/i }));
    await user.type(screen.getByRole("textbox", { name: /folder/i }), "/books");
    await user.type(screen.getByRole("textbox", { name: /name/i }), "Books");
    await user.click(screen.getByRole("button", { name: /^add$/i }));
    expect(calls.some((c) => c.url === "/api/storage/roots")).toBe(true);

    await user.click(screen.getByRole("button", { name: /check my files/i }));
    expect(calls.some((c) => c.url === "/api/storage/scan")).toBe(true);
  });

  it("explains a move before starting it and never deletes the old copy", async () => {
    mockApi([get("/api/storage", ROOTS)]);
    const user = userEvent.setup();
    renderWithProviders(<StoragePanel />);
    const rows = await screen.findAllByRole("listitem");

    await user.click(within(rows[0]!).getByRole("button", { name: /move/i }));
    const dialog = await screen.findByRole("dialog", { name: /move this location/i });
    expect(dialog).toHaveTextContent(/old copy is kept|nothing is deleted/i);
    expect(dialog).toHaveTextContent(/resume/i);
  });
});

describe("Import", () => {
  const REVIEW = {
    upload_id: "u1", format: "cbz", suggested_title: "Chapter one", language: "en", page_count: 18,
    warnings: [], suggestions: [],
  };

  it("reviews a file before importing it", async () => {
    const calls = mockApi([
      post("/api/import/uploads", REVIEW),
      post("/api/import", { import_id: "i1", work_id: "w1", reading_unit_id: "u1", asset_id: "a1",
                            path: "Sequential Art/…", warnings: [] }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ImportPanel />);

    const file = new File([new Uint8Array([80, 75, 3, 4])], "chapter one.cbz", { type: "application/zip" });
    await user.upload(screen.getByLabelText(/choose a file/i), file);

    expect(await screen.findByText("CBZ")).toBeInTheDocument();      // the reviewed format
    expect(screen.getByText(/18 pages/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /title/i })).toHaveValue("Chapter one");

    await user.click(screen.getByRole("button", { name: /^import$/i }));
    const call = calls.find((c) => c.url === "/api/import");
    expect(call).toBeDefined();
    expect((call!.body as { mode: string }).mode).toBe("copy");     // Copy is the default (§37)
  });

  it("offers a confident association as a choice, never as a decision", async () => {
    mockApi([post("/api/import/uploads", {
      ...REVIEW,
      suggestions: [{ work_id: "w9", title: "The Irregular Chronicle", tier: "exact_title", content_type: "manga",
                      confident: true }],
    })]);
    const user = userEvent.setup();
    renderWithProviders(<ImportPanel />);

    const file = new File([new Uint8Array([80, 75, 3, 4])], "one.cbz", { type: "application/zip" });
    await user.upload(screen.getByLabelText(/choose a file/i), file);

    const options = await screen.findByRole("radiogroup", { name: /where should this go/i });
    expect(within(options).getByRole("radio", { name: /the irregular chronicle/i })).toBeInTheDocument();
    expect(within(options).getByRole("radio", { name: /new work/i })).toBeInTheDocument();
  });

  it("says why a file was refused", async () => {
    mockApi([post("/api/import/uploads",
                  { error: { code: "UNSUPPORTED_FILE", message: "this is not a CBZ, PDF or EPUB" } }, 422)]);
    const user = userEvent.setup();
    renderWithProviders(<ImportPanel />);

    // A file with an accepted extension whose contents are not a real archive.
    const file = new File([new Uint8Array([1, 2])], "notes.cbz", { type: "application/zip" });
    await user.upload(screen.getByLabelText(/choose a file/i), file);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not a CBZ, PDF or EPUB/i);
  });
});


describe("Import selection regressions", () => {
  const review = { upload_id: "A", format: "pdf", suggested_title: "First book", language: "en",
    page_count: 4, warnings: [], suggestions: [] };
  const file = (name: string) => new File(["test"], name, { type: "application/pdf" });

  it("removes the previous review when the next file is refused", async () => {
    const user = userEvent.setup();
    const respond = vi.fn().mockResolvedValueOnce(Response.json(review)).mockResolvedValueOnce(
      Response.json({ error: { message: "Invalid PDF" } }, { status: 422 }));
    vi.stubGlobal("fetch", respond);
    renderWithProviders(<ImportPanel />);
    await user.upload(screen.getByLabelText(/choose a file/i), file("a.pdf"));
    expect(await screen.findByRole("button", { name: /^import$/i })).toBeEnabled();
    await user.upload(screen.getByLabelText(/choose a file/i), file("b.pdf"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid PDF");
    expect(screen.queryByRole("button", { name: /^import$/i })).not.toBeInTheDocument();
  });

  it("ignores an older review arriving after the latest file", async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValueOnce(Response.json({ ...review, upload_id: "B", suggested_title: "Second book" })));
    const user = userEvent.setup();
    renderWithProviders(<ImportPanel />);
    await user.upload(screen.getByLabelText(/choose a file/i), file("a.pdf"));
    await user.upload(screen.getByLabelText(/choose a file/i), file("b.pdf"));
    expect(await screen.findByRole("textbox", { name: /title/i })).toHaveValue("Second book");
    await act(async () => finish(Response.json(review)));
    expect(screen.getByRole("textbox", { name: /title/i })).toHaveValue("Second book");
  });

  it("blocks repeat imports while the request is pending", async () => {
    let finish!: (response: Response) => void;
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json(review))
      .mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    vi.stubGlobal("fetch", fetcher);
    const user = userEvent.setup();
    renderWithProviders(<ImportPanel />);
    await user.upload(screen.getByLabelText(/choose a file/i), file("a.pdf"));
    const button = await screen.findByRole("button", { name: /^import$/i });
    await user.dblClick(button);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(button).toBeDisabled();
    await act(async () => finish(Response.json({})));
    expect(await screen.findByRole("status")).toHaveTextContent(/import/i);
  });
});
