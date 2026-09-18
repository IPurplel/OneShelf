/** Master §27, ledger K3: EPUB content is sanitised and rendered in an isolated, script-free frame. */
import { strToU8, zipSync } from "fflate";
import { describe, expect, it } from "vitest";

import { openEpub, sanitiseDocument } from "./epub";

function buildEpub(chapters: Record<string, string>, extra: Record<string, string> = {}): ArrayBuffer {
  const manifest = Object.keys(chapters)
    .map((name, i) => `<item id="c${i}" href="${name}" media-type="application/xhtml+xml"/>`).join("");
  const spine = Object.keys(chapters).map((_, i) => `<itemref idref="c${i}"/>`).join("");
  const files: Record<string, Uint8Array> = {
    "mimetype": strToU8("application/epub+zip"),
    "META-INF/container.xml": strToU8(
      `<?xml version="1.0"?><container version="1.0"
        xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
      </rootfiles></container>`),
    "OEBPS/content.opf": strToU8(
      `<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">
        <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>A Quiet Book</dc:title>
        <dc:language>en</dc:language><dc:creator>A. Writer</dc:creator></metadata>
        <manifest>${manifest}</manifest><spine>${spine}</spine></package>`),
  };
  for (const [name, body] of Object.entries(chapters)) files[`OEBPS/${name}`] = strToU8(body);
  for (const [name, body] of Object.entries(extra)) files[name] = strToU8(body);
  const zipped = zipSync(files);
  return zipped.buffer.slice(zipped.byteOffset, zipped.byteOffset + zipped.byteLength) as ArrayBuffer;
}

const SIMPLE = buildEpub({
  "one.xhtml": "<html><body><h1>Chapter One</h1><p>The quiet begins.</p></body></html>",
  "two.xhtml": "<html><body><h1>Chapter Two</h1><p>And continues quietly.</p></body></html>",
});

describe("EPUB", () => {
  it("reads the package: title, language and spine order", async () => {
    const book = await openEpub(SIMPLE);
    expect(book.title).toBe("A Quiet Book");
    expect(book.language).toBe("en");
    expect(book.creator).toBe("A. Writer");
    expect(book.spine.map((item) => item.href)).toEqual(["OEBPS/one.xhtml", "OEBPS/two.xhtml"]);
    expect(book.spine.map((item) => item.title)).toEqual(["Chapter One", "Chapter Two"]);
  });

  it("gives each chapter its text for logical progress and search", async () => {
    const book = await openEpub(SIMPLE);
    const chapter = await book.chapter(0);
    expect(chapter.text).toContain("The quiet begins.");
    expect(book.spine[0]!.characters).toBeGreaterThan(0);
  });

  it("strips scripts, event handlers and javascript: links", () => {
    const hostile = `<html><body>
      <h1 onclick="steal()">Title</h1>
      <script>fetch('/api/backups', {method: 'POST'})</script>
      <a href="javascript:alert(1)">tap</a>
      <iframe src="https://evil.example"></iframe>
      <img src="x" onerror="fetch('/api/shelf')">
      <svg><use href="https://evil.example/x.svg#a"/></svg>
    </body></html>`;
    const safe = sanitiseDocument(hostile, () => null);
    expect(safe).not.toMatch(/<script/i);
    expect(safe).not.toMatch(/onclick|onerror/i);
    expect(safe).not.toMatch(/javascript:/i);
    expect(safe).not.toMatch(/<iframe/i);
    expect(safe).not.toMatch(/evil\.example/);
    expect(safe).toContain("Title");
  });

  it("keeps a chapter's own images by resolving them inside the book", async () => {
    const withImage = buildEpub(
      { "one.xhtml": `<html><body><img src="images/p1.png" alt="a page"><p>text</p></body></html>` },
      { "OEBPS/images/p1.png": "not-really-a-png" },
    );
    const book = await openEpub(withImage);
    const chapter = await book.chapter(0);
    expect(chapter.html).toContain("blob:");
    expect(chapter.html).toContain('alt="a page"');
  });

  it("refuses something that is not an EPUB rather than guessing", async () => {
    const notAnEpub = new Uint8Array([1, 2, 3, 4]).buffer;
    await expect(openEpub(notAnEpub)).rejects.toThrow(/epub/i);
  });
});
