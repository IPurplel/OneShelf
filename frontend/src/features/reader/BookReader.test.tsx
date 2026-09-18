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

function stubFile(bytes: Uint8Array, contentType: string) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/file")) {
      return new Response(bytes as BodyInit, { status: 200, headers: { "Content-Type": contentType } });
    }
    return new Response(JSON.stringify({ read_state: "unread", fraction: 0, locator: null, revision: 0 }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  }));
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

  it("keeps bookmarks and highlights for this book", async () => {
    stubFile(epubBytes(), "application/epub+zip");
    const user = userEvent.setup();
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    await screen.findByTitle(/book content/i);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/1 of 2/i));
    await user.click(screen.getByRole("button", { name: /bookmark/i }));
    await user.click(screen.getByRole("button", { name: /contents/i }));
    const drawer = await screen.findByRole("dialog", { name: /contents/i });
    await user.click(within(drawer).getByRole("tab", { name: /bookmarks/i }));
    expect(within(drawer).getByText(/chapter one/i)).toBeInTheDocument();
  });

  it("says plainly when the file is not on this device", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ error: { code: "FILE_NOT_AVAILABLE", message: "this reading unit has no downloaded file" } }),
      { status: 404, headers: { "Content-Type": "application/json" } })));
    renderWithProviders(<BookReader unitId="u9" format="epub" workId="w1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/no downloaded file/i);
  });
});
