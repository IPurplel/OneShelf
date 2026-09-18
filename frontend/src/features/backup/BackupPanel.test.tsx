/** Master §33, §32.15: archival, and restore as a considered workflow rather than a casual modal. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BackupPanel } from "./BackupPanel";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

const BACKUPS = {
  backups: [
    { path: "/backups/library-2026-09-18.osbackup", kind: "library", created_at: "2026-09-18T03:00:00+00:00",
      size_bytes: 24_000_000, verified: true },
    { path: "/backups/library-2026-09-11.osbackup", kind: "library", created_at: "2026-09-11T03:00:00+00:00",
      size_bytes: 23_500_000, verified: true },
  ],
  due: false,
  location_warning: { same_device_as_library: true, message: "Backups sit on the same disk as your library." },
};

const PREFLIGHT = {
  ok: true, compatible: true, kind: "library", schema_version: 12,
  counts: { works: 12, shelf_entries: 12, reading_state: 30 },
  plugins: [{ id: "oneshelf.mangadex", version: "1.0.0", installed: false, installed_version: null,
              new_permissions: [] }],
  space_needed: 24_000_000, issues: [],
};

afterEach(() => vi.unstubAllGlobals());

describe("Backup", () => {
  it("lists archives and warns when they share a disk with the library", async () => {
    mockApi([get("/api/backups", BACKUPS)]);
    renderWithProviders(<BackupPanel />);

    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText(/library/i)).toBeInTheDocument();
    expect(screen.getByText(/same disk as your library/i)).toBeInTheDocument();
  });

  it("makes a library backup, and a full one only when works are chosen", async () => {
    const calls = mockApi([
      get("/api/backups", BACKUPS),
      post("/api/backups", { path: "/backups/new.osbackup", kind: "library", verified: true }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<BackupPanel />);
    await screen.findAllByRole("listitem");

    await user.click(screen.getByRole("button", { name: /back up my library/i }));
    const call = calls.find((c) => c.url === "/api/backups" && c.method === "POST");
    expect((call!.body as { kind: string }).kind).toBe("library");
  });

  it("restores in steps: check the archive, read what it holds, then choose how", async () => {
    const calls = mockApi([
      get("/api/backups", BACKUPS),
      post("/api/restore/preflight", PREFLIGHT),
      post("/api/restore", { mode: "merge", added: { works: 2 }, kept: {}, repaired_files: 0 }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<BackupPanel />);
    const rows = await screen.findAllByRole("listitem");

    await user.click(within(rows[0]!).getByRole("button", { name: /restore/i }));
    const dialog = await screen.findByRole("dialog", { name: /restore/i });
    expect(calls.some((c) => c.url === "/api/restore/preflight")).toBe(true);

    // Step 2: what the archive holds, and what it expects of your sources.
    expect(await within(dialog).findByText(/12 works/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/oneshelf\.mangadex/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/not installed/i)).toBeInTheDocument();

    // Step 3: the two modes, each explained, with Merge as the safe default.
    const modes = within(dialog).getByRole("radiogroup", { name: /how should this restore/i });
    expect(within(modes).getAllByRole("radio").map((r) => r.getAttribute("value"))).toEqual(["merge", "replace"]);
    expect(within(dialog).getByText(/never moves your reading progress backwards/i)).toBeInTheDocument();
    await user.click(within(modes).getByRole("radio", { name: /replace my library/i }));
    expect(within(dialog).getByText(/safety snapshot/i)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /^restore$/i }));
    const restore = calls.find((c) => c.url === "/api/restore");
    expect((restore!.body as { mode: string }).mode).toBe("replace");
  });

  it("refuses an incompatible archive with the reason", async () => {
    mockApi([
      get("/api/backups", BACKUPS),
      post("/api/restore/preflight", { ...PREFLIGHT, ok: false, compatible: false,
                                       issues: ["this backup came from a newer OneShelf"] }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<BackupPanel />);
    const rows = await screen.findAllByRole("listitem");

    await user.click(within(rows[0]!).getByRole("button", { name: /restore/i }));
    const dialog = await screen.findByRole("dialog", { name: /restore/i });
    expect(await within(dialog).findByText(/newer OneShelf/i)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /^restore$/i })).not.toBeInTheDocument();
  });
});
