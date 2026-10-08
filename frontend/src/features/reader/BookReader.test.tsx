/** Master §26.22, §27: the Book Reader renders untrusted documents in isolation. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { strToU8, zipSync } from "fflate";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BookReader } from "./BookReader";
import { renderWithProviders } from "@/test/render";

function epubBytes(): Uint8Array {
  return zipSync({
    "mimetype": strToU8("application/epub+zip"),
    "META-INF/container.xml": strToU8(
      `<?xml version="1.0"?><container version="1.0"
        xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
      </rootfiles></container>`),
    "OEBPS/content.opf": strToU8(
      `<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">
        <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>A Quiet Book</dc:title></metadata>
        <manifest><item id="c0" href="one.xhtml" media-type="application/xhtml+xml"/>
        <item id="c1" href="two.xhtml" media-type="application/xhtml+xml"/></manifest>
        <spine><itemref idref="c0"/><itemref idref="c1"/></spine></package>`),
    "OEBPS/one.xhtml": strToU8(
      "<html><body><h1>Chapter One</h1><p>The quiet begins.</p><script>fetch('/api/backups')</script></body></html>"),
    "OEBPS/two.xhtml": strToU8("<html><body><h1>Chapter Two</h1><p>Rain on the window.</p></body></html>"),
  });
}

function epubWithSpine(spine: string): Uint8Array {
  return zipSync({
    "META-INF/container.xml": strToU8('<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>'),
    "OEBPS/content.opf": strToU8(`<package><metadata><title>Small Book</title></metadata>
      <manifest><item id="c0" href="one.xhtml"/></manifest><spine>${spine}</spine></package>`),
    "OEBPS/one.xhtml": strToU8("<html><body><p>One readable chapter.</p></body></html>"),
  });
}

function epubWithDirection(language: string | null, chapter: string): Uint8Array {
  return zipSync({
    "META-INF/container.xml": strToU8('<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>'),
    "OEBPS/content.opf": strToU8(`<package><metadata><title>Direction test</title>${language ? `<language>${language}</language>` : ""}</metadata>
      <manifest><item id="c0" href="one.xhtml"/></manifest><spine><itemref idref="c0"/></spine></package>`),
    "OEBPS/one.xhtml": strToU8(chapter),
  });
}

type Call = { url: string; method: string; body: unknown };

/** The file, the marks the library holds, and progress — the three things the Book Reader talks to. */
function stubFile(bytes: Uint8Array, contentType: string, progress?: Record<string, unknown>,
                  failures?: { bookmarks?: boolean; highlights?: boolean }): Call[] {
  const calls: Call[] = [];
  const marks: { bookmarks: unknown[]; highlights: unknown[] } = { bookmarks: [], highlights: [] };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ url, method, body });
    if (url.includes("/file")) {
      return new Response(bytes as BodyInit, { status: 200, headers: { "Content-Type": contentType } });
    }
    const json = (payload: unknown) => new Response(JSON.stringify(payload), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
    if (url.endsWith("/marks")) return json(marks);
    if (url.endsWith("/bookmarks") && method === "POST") {
      if (failures?.bookmarks) return new Response(JSON.stringify({ error: { message: "Marks unavailable" } }),
        { status: 503, headers: { "Content-Type": "application/json" } });
      const made = { id: `b${marks.bookmarks.length + 1}`, locator: body.locator, label: body.label,
                     created_at: "2026-09-18T10:00:00+00:00" };
      marks.bookmarks.push(made);
      return json(made);
    }
    if (url.endsWith("/highlights") && method === "POST") {
      if (failures?.highlights) return new Response(JSON.stringify({ error: { message: "Marks unavailable" } }),
        { status: 503, headers: { "Content-Type": "application/json" } });
      const made = { id: `h${marks.highlights.length + 1}`, locator: body.locator, text: body.text,
                     colour: "yellow", created_at: "2026-09-18T10:00:00+00:00" };
      marks.highlights.push(made);
      return json(made);
    }
    return json(progress ?? { read_state: "unread", fraction: 0, locator: null, revision: 0 });
  }));
  return calls;
}

/** A real DOM selection over one text node, the way a reader makes one with the pointer. */
function selectWithin(element: HTMLElement, start: number, end: number) {
  const node = element.firstChild!;
  const range = document.createRange();
  range.setStart(node, start);
  range.setEnd(node, end);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
}

afterEach(() => vi.unstubAllGlobals());

describe("Book Reader (EPUB)", () => {
  it("shows a recoverable localized error for an empty spine instead of 1 of 0", async () => {
    stubFile(epubWithSpine(""), "application/epub+zip");
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" trackId="t-ar" />, { language: "ar" });
    expect(await screen.findByRole("alert")).toHaveTextContent("لا يحتوي هذا الكتاب على فصول قابلة للقراءة");
    expect(screen.queryByText(/1 of 0|1 من 0/)).toBeNull();
    expect(screen.getByRole("link", { name: /العودة إلى العمل/i }))
      .toHaveAttribute("href", "/works/w1?track=t-ar");
    expect(screen.getByRole("button", { name: /أعد المحاولة/i })).toBeInTheDocument();
  });

  it("reports a spine whose chapter files are all missing", async () => {
    stubFile(epubWithSpine('<itemref idref="missing"/>'), "application/epub+zip");
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/no readable chapters/i);
  });

  it("shows a localized recovery message for a malformed EPUB", async () => {
    stubFile(strToU8("not a zip"), "application/epub+zip");
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />, { language: "ar" });
    expect(await screen.findByRole("alert")).toHaveTextContent("تعذّر فتح ملف EPUB");
    expect(screen.getByRole("link", { name: /العودة إلى العمل/i })).toBeInTheDocument();
  });

  it("still opens a valid one-chapter EPUB", async () => {
    stubFile(epubWithSpine('<itemref idref="c0"/>'), "application/epub+zip");
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 of 1"));
    await waitFor(() => expect(screen.getByTitle(/book content/i).getAttribute("srcdoc"))
      .toContain("One readable chapter."));
  });

  it.each([
    ["en", "en", "<html><body><p>An English paragraph.</p></body></html>", "ltr"],
    ["ar", null, "<html><body><p>An English paragraph.</p></body></html>", "ltr"],
    ["en", "ar", "<html><body><p>فقرة عربية للقراءة.</p></body></html>", "rtl"],
    ["ar", "en", "<html dir=\"rtl\"><body><p>فقرة عربية للقراءة.</p></body></html>", "rtl"],
  ] as const)("uses content direction for %s UI and %s metadata", async (ui, metadata, chapter, expected) => {
    stubFile(epubWithDirection(metadata, chapter), "application/epub+zip");
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />, { language: ui });
    await waitFor(() => expect(document.querySelector("iframe.book__frame")?.getAttribute("srcdoc"))
      .toContain(`<html dir="${expected}">`));
  });

  it("renders the chapter inside a sandboxed frame that cannot run scripts or reach the app", async () => {
    stubFile(epubBytes(), "application/epub+zip");
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);

    const frame = await screen.findByTitle(/book content/i);
    expect(frame.tagName).toBe("IFRAME");
    expect(frame).toHaveAttribute("sandbox", "");                       // no scripts, no same-origin
    await waitFor(() => expect(frame.getAttribute("srcdoc") ?? "").toContain("The quiet begins."));
    const html = frame.getAttribute("srcdoc") ?? "";
    expect(html).not.toMatch(/<script/i);
    expect(html).toContain("Content-Security-Policy");
  });

  it("moves through the book by chapter and reports logical progress", async () => {
    stubFile(epubBytes(), "application/epub+zip");
    const user = userEvent.setup();
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    await screen.findByTitle(/book content/i);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/1 of 2/i));
    await user.click(screen.getByRole("button", { name: /next chapter/i }));
    expect(await screen.findByRole("status")).toHaveTextContent(/2 of 2/i);
    expect(screen.getByTitle(/book content/i).getAttribute("srcdoc")).toContain("Rain on the window");
  });

  it("searches the book's own text and offers the chapters that match", async () => {
    stubFile(epubBytes(), "application/epub+zip");
    const user = userEvent.setup();
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    await screen.findByTitle(/book content/i);

    await user.click(screen.getByRole("button", { name: /search/i }));
    const panel = await screen.findByRole("dialog", { name: /search/i });
    await user.type(within(panel).getByRole("searchbox"), "rain");
    const hits = await within(panel).findAllByRole("button", { name: /chapter two/i });
    expect(hits.length).toBeGreaterThan(0);
  });

  it("keeps a bookmark with the library rather than in this browser", async () => {
    const calls = stubFile(epubBytes(), "application/epub+zip");
    const user = userEvent.setup();
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    await screen.findByTitle(/book content/i);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/1 of 2/i));
    await user.click(screen.getByRole("button", { name: /bookmark/i }));

    const made = calls.find((c) => c.url.endsWith("/bookmarks") && c.method === "POST");
    expect(made?.body).toMatchObject({ locator: { chapter: 0 }, label: "Chapter One",
      operation_id: expect.any(String) });

    await user.click(screen.getByRole("button", { name: /contents/i }));
    const drawer = await screen.findByRole("dialog", { name: /contents/i });
    await user.click(within(drawer).getByRole("tab", { name: /bookmarks/i }));
    expect(await within(drawer).findByText(/chapter one/i)).toBeInTheDocument();
  });

  it("reports a failed bookmark and retries it without claiming it was saved", async () => {
    const failures = { bookmarks: true };
    const calls = stubFile(epubBytes(), "application/epub+zip", undefined, failures);
    const user = userEvent.setup();
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 of 2"));
    await user.click(screen.getByRole("button", { name: /bookmark this place/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not save.*marks unavailable/i);
    await user.click(screen.getByRole("button", { name: /contents/i }));
    let drawer = await screen.findByRole("dialog", { name: /contents/i });
    await user.click(within(drawer).getByRole("tab", { name: /bookmarks/i }));
    expect(within(drawer).queryByText(/chapter one/i)).toBeNull();
    await user.keyboard("{Escape}");
    failures.bookmarks = false;
    await user.click(screen.getByRole("button", { name: /retry saving mark/i }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    await user.click(screen.getByRole("button", { name: /contents/i }));
    drawer = await screen.findByRole("dialog", { name: /contents/i });
    await user.click(within(drawer).getByRole("tab", { name: /bookmarks/i }));
    expect(await within(drawer).findByText(/chapter one/i)).toBeInTheDocument();
    const attempts = calls.filter(call => call.url.endsWith("/bookmarks") && call.method === "POST");
    expect(attempts).toHaveLength(2);
    expect((attempts[0]?.body as { operation_id: string }).operation_id)
      .toBe((attempts[1]?.body as { operation_id: string }).operation_id);
  });

  it("captures a highlight from the chapter's own text, and keeps it with the library", async () => {
    const calls = stubFile(epubBytes(), "application/epub+zip");
    const user = userEvent.setup();
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    await screen.findByTitle(/book content/i);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/1 of 2/i));

    await user.click(screen.getByRole("button", { name: /highlight/i }));
    const panel = await screen.findByRole("dialog", { name: /highlight/i });
    // The pane holds the chapter as text the app itself extracted — never the document's own markup.
    const passage = await within(panel).findByText(/the quiet begins/i);
    expect(passage.querySelector("script")).toBeNull();

    const start = passage.textContent!.indexOf("quiet");
    selectWithin(passage, start, start + "quiet".length);
    await user.click(within(panel).getByRole("button", { name: /keep this highlight/i }));

    const made = calls.find((c) => c.url.endsWith("/highlights") && c.method === "POST");
    expect(made?.body).toMatchObject({ text: "quiet",
                                       locator: { chapter: 0, start, end: start + "quiet".length } });
  });

  it("reports a failed highlight save through the same mark error surface", async () => {
    const failures = { highlights: true };
    const calls = stubFile(epubBytes(), "application/epub+zip", undefined, failures);
    const user = userEvent.setup();
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 of 2"));
    await user.click(screen.getByRole("button", { name: /highlight/i }));
    const panel = await screen.findByRole("dialog", { name: /highlight/i });
    const passage = await within(panel).findByText(/the quiet begins/i);
    const start = passage.textContent!.indexOf("quiet");
    selectWithin(passage, start, start + 5);
    await user.click(within(panel).getByRole("button", { name: /keep this highlight/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not save.*marks unavailable/i);
    failures.highlights = false;
    await user.click(screen.getByRole("button", { name: /retry saving mark/i }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    const attempts = calls.filter(call => call.url.endsWith("/highlights") && call.method === "POST");
    expect(attempts).toHaveLength(2);
    expect((attempts[0]?.body as { operation_id: string }).operation_id)
      .toBe((attempts[1]?.body as { operation_id: string }).operation_id);
  });

  it("says when nothing is selected rather than keeping an empty highlight", async () => {
    const calls = stubFile(epubBytes(), "application/epub+zip");
    const user = userEvent.setup();
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    await screen.findByTitle(/book content/i);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/1 of 2/i));

    await user.click(screen.getByRole("button", { name: /highlight/i }));
    const panel = await screen.findByRole("dialog", { name: /highlight/i });
    await user.click(within(panel).getByRole("button", { name: /keep this highlight/i }));

    expect(within(panel).getByRole("alert")).toHaveTextContent(/select the words/i);
    expect(calls.some((c) => c.url.endsWith("/highlights") && c.method === "POST")).toBe(false);
  });

  it("says plainly when the file is not on this device", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ error: { code: "FILE_NOT_AVAILABLE", message: "this reading unit has no downloaded file" } }),
      { status: 404, headers: { "Content-Type": "application/json" } })));
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/no downloaded file/i);
  });

  it("opens the book at the chapter it was left on", async () => {
    stubFile(epubBytes(), "application/epub+zip",
             { read_state: "partial", fraction: 0.5, locator: { chapter: 1 }, revision: 3 });
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    await screen.findByTitle(/book content/i);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/2 of 2/i));
    await waitFor(() =>
      expect(screen.getByTitle(/book content/i).getAttribute("srcdoc")).toContain("Rain on the window"));
  });

  // §26.22a: the comfort settings a book reader needs — and none of them reach the book itself. The
  // typography is OneShelf's own stylesheet inside the frame; the frame keeps its empty sandbox and its
  // own CSP (§27, ledger K3).
  it("lets the reader set type, spacing, margins and theme, without loosening the frame", async () => {
    stubFile(epubBytes(), "application/epub+zip");
    const user = userEvent.setup();
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    const frame = await screen.findByTitle(/book content/i);
    await waitFor(() => expect(frame.getAttribute("srcdoc") ?? "").toContain("The quiet begins."));

    await user.click(screen.getByRole("button", { name: /reading comfort/i }));
    const panel = await screen.findByRole("dialog", { name: /reading comfort/i });
    await user.click(within(panel).getByRole("radio", { name: /larger/i }));
    await user.click(within(panel).getByRole("radio", { name: /sepia/i }));
    await user.click(within(panel).getByRole("radio", { name: /wide/i }));
    await user.keyboard("{Escape}");

    const html = screen.getByTitle(/book content/i).getAttribute("srcdoc") ?? "";
    expect(html).toMatch(/font-size:\s*21px/);
    expect(html).toMatch(/#f4ecd8/i);                       // the sepia page
    expect(html).toMatch(/padding:\s*4vh 12vw/);
    expect(screen.getByTitle(/book content/i)).toHaveAttribute("sandbox", "");
    expect(html).toContain("Content-Security-Policy");
    expect(html).not.toMatch(/<script/i);
  });

  it("remembers the reading comfort for this book", async () => {
    stubFile(epubBytes(), "application/epub+zip");
    const user = userEvent.setup();
    const first = renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    await screen.findByTitle(/book content/i);
    await user.click(screen.getByRole("button", { name: /reading comfort/i }));
    await user.click(within(await screen.findByRole("dialog", { name: /reading comfort/i }))
      .getByRole("radio", { name: /larger/i }));
    first.unmount();

    stubFile(epubBytes(), "application/epub+zip");
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    const frame = await screen.findByTitle(/book content/i);
    await waitFor(() => expect(frame.getAttribute("srcdoc") ?? "").toMatch(/font-size:\s*21px/));
  });
});

it("requests the explicit EPUB format when a unit also has PDF", async () => {
  const calls = stubFile(epubBytes(), "application/epub+zip");
  renderWithProviders(<BookReader unitId="mixed" format="epub" workId="w1" />);
  await waitFor(() => expect(screen.getByTitle(/book content/i).getAttribute("srcdoc")).toContain("The quiet begins."));
  expect(calls.some(call => call.url === "/api/reader/units/mixed/file?format=epub")).toBe(true);
});

it("clears a failed document when a new book is opened in the mounted reader", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "MISSING", message: "Old file missing" } }), { status: 404 })));
  const { rerender } = renderWithProviders(<BookReader unitId="old" format="epub" workId="w1" />);
  // Offline or unavailable old content must never remain sticky on the next unit.
  await screen.findByRole("alert");
  stubFile(epubBytes(), "application/epub+zip");
  const { TestProviders } = await import("@/test/providers");
  rerender(<TestProviders><BookReader unitId="new" format="epub" workId="w1" /></TestProviders>);
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  await waitFor(() => expect(screen.getByTitle(/book content/i).getAttribute("srcdoc")).toContain("The quiet begins."));
});
