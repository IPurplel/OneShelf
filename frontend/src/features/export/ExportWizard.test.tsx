/** Master §34, §32.16: Content → Format → Destination → Review, and never a silent download. */
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExportWizard } from "./ExportWizard";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

const WORK = {
  work: { id: "w1", title: "The Irregular Chronicle", original_title: null, creator: null, description: null,
          content_type: "manga", content_type_source: "source", aliases: [] },
  shelf: { on_shelf: true, favorite: false, pinned: false, completed: false },
  follow: { following: false, preferred_source_id: null, track_id: null, language: null, last_successful_at: null },
  tracks: [{ id: "t1", source_id: "local", language: "en", kind: "local", availability: "available", unit_count: 2 }],
  selected_track_id: "t1",
  units: [
    { id: "u1", title: "Prologue", number: null, unit_type: "prologue", volume: null, order: 1, release_date: null,
      availability: "available", url: null, downloaded: true, formats: ["cbz"], read_state: "read", fraction: 1,
      read_at: null },
    { id: "u2", title: "Chapter 1", number: "1", unit_type: "chapter", volume: null, order: 2, release_date: null,
      availability: "available", url: null, downloaded: false, formats: [], read_state: "unread", fraction: 0,
      read_at: null },
  ],
  continue_unit_id: "u1",
};

const PREVIEW = { files: 1, total_bytes: 12_000_000, missing_units: ["u2"], choices: [
  "export_downloaded_only", "download_missing_then_export", "cancel"],
  disclosure: { message: "This will also permanently download these items into your OneShelf library before exporting them.",
                units: ["u2"], choices: ["export_downloaded_only", "download_missing_then_export", "cancel"] } };

afterEach(() => vi.unstubAllGlobals());

async function openWizard() {
  const user = userEvent.setup();
  renderWithProviders(<ExportWizard workId="w1" onClose={() => {}} />);
  await screen.findByRole("dialog", { name: /export/i });
  return user;
}

describe("Export", () => {
  it("keeps the newest destination preview and exports the same selection", async () => {
    let resolveA!: (response: Response) => void;
    const a = new Promise<Response>((resolve) => { resolveA = resolve; });
    const requests: { path: string; body: Record<string, unknown> }[] = [];
    vi.stubGlobal("fetch", vi.fn((path: string, init?: RequestInit) => {
      if (path.startsWith("/api/works/")) return Promise.resolve(Response.json(WORK));
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      requests.push({ path, body });
      if (path === "/api/export/preview") return body.destination === "/A" ? a
        : Promise.resolve(Response.json({ ...PREVIEW, files: 2, total_bytes: 2000, missing_units: [], disclosure: null }));
      return Promise.resolve(Response.json({ job_id: "j1", state: "completed", copied: 2, skipped: 0,
        failed: 0, errors: [] }));
    }));
    const user = await openWizard();
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Next" }));
    await user.click(within(dialog).getByRole("button", { name: "Next" }));
    const field = within(dialog).getByRole("textbox");
    await user.type(field, "/A");
    await user.click(within(dialog).getByRole("button", { name: "Next" }));
    await user.clear(field);
    await user.type(field, "/B");
    await user.click(within(dialog).getByRole("button", { name: "Next" }));
    expect(await within(dialog).findByText("2 files, 2.0 KB.")).toBeInTheDocument();
    await act(async () => resolveA(Response.json({ ...PREVIEW, files: 1 })));
    expect(within(dialog).getByText("2 files, 2.0 KB.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Export" }));
    expect(requests.at(-1)).toMatchObject({ path: "/api/export", body: { destination: "/B" } });
  });

  it.each(["failure", "older same-destination success"] as const)(
    "ignores a stale preview %s after a newer generation", async (late) => {
      let finishFirst!: (response: Response) => void;
      const first = new Promise<Response>((resolve) => { finishFirst = resolve; });
      let checks = 0;
      vi.stubGlobal("fetch", vi.fn((path: string) => {
        if (path.startsWith("/api/works/")) return Promise.resolve(Response.json(WORK));
        if (path === "/api/export/preview") {
          checks += 1;
          return checks === 1 ? first : Promise.resolve(Response.json({ ...PREVIEW, files: 2,
            total_bytes: 2000, missing_units: [], disclosure: null }));
        }
        return Promise.resolve(Response.json({}));
      }));
      const user = await openWizard();
      const dialog = screen.getByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: "Next" }));
      await user.click(within(dialog).getByRole("button", { name: "Next" }));
      const field = within(dialog).getByRole("textbox");
      await user.type(field, "/A");
      await user.click(within(dialog).getByRole("button", { name: "Next" }));
      await user.clear(field);
      await user.type(field, "/B");
      if (late === "older same-destination success") {
        await user.clear(field);
        await user.type(field, "/A");
      }
      await user.click(within(dialog).getByRole("button", { name: "Next" }));
      await within(dialog).findByText("2 files, 2.0 KB.");
      await act(async () => finishFirst(late === "failure"
        ? Response.json({ error: { message: "Old preview failed" } }, { status: 503 })
        : Response.json({ ...PREVIEW, files: 1 })));
      expect(within(dialog).getByText("2 files, 2.0 KB.")).toBeInTheDocument();
      expect(within(dialog).queryByText("Old preview failed")).toBeNull();
    });

  it.each([[0, "0 files"], [1, "1 file"], [2, "2 files"]])("pluralizes %i files as %s", async (count, expected) => {
    mockApi([get("/api/works/w1", WORK), post("/api/export/preview",
      { ...PREVIEW, files: count, missing_units: [], disclosure: null })]);
    const user = await openWizard();
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Next" }));
    await user.click(within(dialog).getByRole("button", { name: "Next" }));
    await user.type(within(dialog).getByRole("textbox"), "/destination");
    await user.click(within(dialog).getByRole("button", { name: "Next" }));
    expect(await within(dialog).findByText(new RegExp(`^${expected},`))).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent("file(s)");
  });
  it("loads the Work track selected on the Details page", async () => {
    const arabic = { ...WORK, tracks: [...WORK.tracks, { ...WORK.tracks[0], id: "t-ar", source_id: "alpha", language: "ar" }],
      selected_track_id: "t-ar", units: [{ ...WORK.units[0], id: "u-ar", title: "الفصل ١" }] };
    const calls = mockApi([get("/api/works/w1", arabic)]);
    renderWithProviders(<ExportWizard workId="w1" trackId="t-ar" onClose={() => {}} />);
    expect(await screen.findByText("الفصل ١")).toBeInTheDocument();
    expect(calls).toContainEqual({ url: "/api/works/w1?track_id=t-ar", method: "GET", body: undefined });
  });

  it("walks content, format, destination and review in that order", async () => {
    mockApi([get("/api/works/w1", WORK), post("/api/export/preview", { ...PREVIEW, missing_units: [], disclosure: null })]);
    const user = await openWizard();
    const dialog = screen.getByRole("dialog", { name: /export/i });

    expect(within(dialog).getByRole("group", { name: /what to export/i })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /next/i }));
    expect(within(dialog).getByRole("radiogroup", { name: /how to package/i })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /next/i }));
    expect(within(dialog).getByRole("textbox", { name: /where should these files go/i })).toBeInTheDocument();
  });

  it("checks the destination before the last step and shows what will be copied", async () => {
    const calls = mockApi([get("/api/works/w1", WORK),
                           post("/api/export/preview", { ...PREVIEW, missing_units: [], disclosure: null })]);
    const user = await openWizard();
    const dialog = screen.getByRole("dialog", { name: /export/i });

    await user.click(within(dialog).getByRole("button", { name: /next/i }));
    await user.click(within(dialog).getByRole("button", { name: /next/i }));
    await user.type(within(dialog).getByRole("textbox", { name: /where should these files go/i }), "/usb");
    await user.click(within(dialog).getByRole("button", { name: /next/i }));

    expect(calls.some((c) => c.url === "/api/export/preview")).toBe(true);
    expect(await within(dialog).findByText(/1 file/i)).toBeInTheDocument();
  });

  it("never downloads missing content without saying so first", async () => {
    const calls = mockApi([get("/api/works/w1", WORK), post("/api/export/preview", PREVIEW),
                           post("/api/export", { job_id: "j1", state: "completed", copied: 2, skipped: 0, failed: 0,
                                                 errors: [] })]);
    const user = await openWizard();
    const dialog = screen.getByRole("dialog", { name: /export/i });

    await user.click(within(dialog).getByRole("button", { name: /next/i }));
    await user.click(within(dialog).getByRole("button", { name: /next/i }));
    await user.type(within(dialog).getByRole("textbox", { name: /where should these files go/i }), "/usb");
    await user.click(within(dialog).getByRole("button", { name: /next/i }));

    expect(await within(dialog).findByText(/permanently download/i)).toBeInTheDocument();
    const choices = within(dialog).getByRole("radiogroup", { name: /some of this is not downloaded/i });
    expect(within(choices).getAllByRole("radio").map((r) => r.getAttribute("value")))
      .toEqual(["export_downloaded_only", "download_missing_then_export"]);

    await user.click(within(choices).getByRole("radio", { name: /download the missing/i }));
    await user.click(within(dialog).getByRole("button", { name: /^export$/i }));

    const call = calls.find((c) => c.url === "/api/export" && c.method === "POST");
    expect(call).toBeDefined();
    const body = call!.body as { missing_policy: string; acknowledge_permanent_download: boolean };
    expect(body.missing_policy).toBe("download_missing_then_export");
    expect(body.acknowledge_permanent_download).toBe(true);     // INV-21
  });

  it("reports the outcome plainly", async () => {
    mockApi([get("/api/works/w1", WORK), post("/api/export/preview", { ...PREVIEW, missing_units: [], disclosure: null }),
             post("/api/export", { job_id: "j1", state: "completed", copied: 1, skipped: 0, failed: 0, errors: [] })]);
    const user = await openWizard();
    const dialog = screen.getByRole("dialog", { name: /export/i });

    await user.click(within(dialog).getByRole("button", { name: /next/i }));
    await user.click(within(dialog).getByRole("button", { name: /next/i }));
    await user.type(within(dialog).getByRole("textbox", { name: /where should these files go/i }), "/usb");
    await user.click(within(dialog).getByRole("button", { name: /next/i }));
    await user.click(await within(dialog).findByRole("button", { name: /^export$/i }));

    expect(await within(dialog).findByText(/copied 1 file/i)).toBeInTheDocument();
  });
});
