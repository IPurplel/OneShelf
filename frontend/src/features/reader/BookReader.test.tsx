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

type Call = { url: string; method: string; body: unknown };

/** The file, the marks the library holds, and progress — the three things the Book Reader talks to. */
function stubFile(bytes: Uint8Array, contentType: string): Call[] {
  const calls: Call[] = [];
  const marks: { bookmarks: unknown[]; highlights: unknown[] } = { bookmarks: [], highlights: [] };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ url, method, body });
    if (url.endsWith("/file")) {
      return new Response(bytes as BodyInit, { status: 200, headers: { "Content-Type": contentType } });
    }
    const json = (payload: unknown) => new Response(JSON.stringify(payload), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
    if (url.endsWith("/marks")) return json(marks);
    if (url.endsWith("/bookmarks") && method === "POST") {
      const made = { id: `b${marks.bookmarks.length + 1}`, locator: body.locator, label: body.label,
                     created_at: "2026-09-18T10:00:00+00:00" };
      marks.bookmarks.push(made);
      return json(made);
    }
    if (url.endsWith("/highlights") && method === "POST") {
      const made = { id: `h${marks.highlights.length + 1}`, locator: body.locator, text: body.text,
                     colour: "yellow", created_at: "2026-09-18T10:00:00+00:00" };
      marks.highlights.push(made);
      return json(made);
    }
    return json({ read_state: "unread", fraction: 0, locator: null, revision: 0 });
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
    expect(made?.body).toEqual({ locator: { chapter: 0 }, label: "Chapter One" });

    await user.click(screen.getByRole("button", { name: /contents/i }));
    const drawer = await screen.findByRole("dialog", { name: /contents/i });
    await user.click(within(drawer).getByRole("tab", { name: /bookmarks/i }));
    expect(await within(drawer).findByText(/chapter one/i)).toBeInTheDocument();
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
});
