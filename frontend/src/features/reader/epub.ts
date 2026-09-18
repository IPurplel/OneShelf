import { unzipSync } from "fflate";

/**
 * A small EPUB reader (Master §26.22) with isolation as its first concern (§27, ledger K3).
 *
 * Chapter markup is untrusted: it is parsed, stripped of anything executable or off-book, and only then
 * handed to a sandboxed frame with no scripts and an opaque origin. Resources are resolved inside the
 * book itself and served as blob URLs, so a document can never reach the network, the session, or any
 * application action.
 */

export type SpineItem = { id: string; href: string; title: string; characters: number };

export type Chapter = { href: string; html: string; text: string };

export type Epub = {
  title: string;
  language: string | null;
  creator: string | null;
  spine: SpineItem[];
  chapter: (index: number) => Promise<Chapter>;
  characters: number;
  close: () => void;
};

const TEXT = new TextDecoder("utf-8");

const REMOVED_TAGS = ["script", "iframe", "frame", "object", "embed", "link", "meta", "base", "form"];
const ALLOWED_LINK_SCHEMES = ["http:", "https:", "mailto:"];

function parse(xml: string): Document {
  return new DOMParser().parseFromString(xml, "application/xml");
}

function resolveHref(base: string, href: string): string {
  const parts = base.split("/").slice(0, -1);
  for (const segment of href.split("/")) {
    if (segment === "." || segment === "") continue;
    if (segment === "..") parts.pop();
    else parts.push(segment);
  }
  return parts.join("/");
}

/**
 * Remove everything a document could act with. `resource` resolves a book-relative path to a URL we
 * created ourselves; anything it cannot resolve is dropped rather than left pointing outward.
 */
export function sanitiseDocument(html: string, resource: (href: string) => string | null): string {
  const document_ = new DOMParser().parseFromString(html, "text/html");

  for (const tag of REMOVED_TAGS) {
    for (const element of Array.from(document_.getElementsByTagName(tag))) element.remove();
  }

  const walk = document_.createTreeWalker(document_, NodeFilter.SHOW_ELEMENT);
  const elements: Element[] = [];
  while (walk.nextNode()) elements.push(walk.currentNode as Element);

  for (const element of elements) {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      const value = attribute.value.trim();

      if (name.startsWith("on")) {                       // no event handlers, ever
        element.removeAttribute(attribute.name);
        continue;
      }
      if (name === "style" && /expression|url\s*\(/i.test(value)) {
        element.removeAttribute(attribute.name);
        continue;
      }
      if (["href", "src", "xlink:href", "poster", "data", "srcset"].includes(name)) {
        if (/^\s*javascript:/i.test(value)) {
          element.removeAttribute(attribute.name);
          continue;
        }
        const absolute = /^[a-z][a-z0-9+.-]*:/i.test(value) || value.startsWith("//");
        if (absolute) {
          const scheme = `${value.split(":", 1)[0]!.toLowerCase()}:`;
          const isPlainLink = name === "href" && element.tagName.toLowerCase() === "a";
          // Anything that would fetch from outside the book is dropped; a plain link may stay.
          if (!isPlainLink || !ALLOWED_LINK_SCHEMES.includes(scheme)) element.removeAttribute(attribute.name);
          continue;
        }
        const resolved = resource(value);
        if (resolved === null) element.removeAttribute(attribute.name);
        else element.setAttribute(attribute.name, resolved);
      }
    }
  }
  return document_.body?.innerHTML ?? "";
}

export async function openEpub(data: ArrayBuffer): Promise<Epub> {
  let files: Record<string, Uint8Array>;
  try {
    files = unzipSync(new Uint8Array(data));
  } catch {
    throw new Error("This file is not an EPUB.");
  }

  const container = files["META-INF/container.xml"];
  if (container === undefined) throw new Error("This EPUB has no container: it may be damaged.");
  const rootPath = parse(TEXT.decode(container)).querySelector("rootfile")?.getAttribute("full-path");
  if (!rootPath || files[rootPath] === undefined) throw new Error("This EPUB has no package document.");

  const opf = parse(TEXT.decode(files[rootPath]!));
  const manifest = new Map<string, string>();
  for (const item of Array.from(opf.getElementsByTagName("item"))) {
    const id = item.getAttribute("id");
    const href = item.getAttribute("href");
    if (id && href) manifest.set(id, resolveHref(rootPath, href));
  }

  // Chapter names come from the book's own table of contents, not from manifest ids.
  const titles = tableOfContents(opf, manifest, files, rootPath);

  const spine: SpineItem[] = [];
  for (const reference of Array.from(opf.getElementsByTagName("itemref"))) {
    const id = reference.getAttribute("idref");
    const href = id ? manifest.get(id) : undefined;
    if (!id || href === undefined || files[href] === undefined) continue;
    const raw = TEXT.decode(files[href]!);
    const text = stripTags(raw);
    spine.push({ id, href, title: titles.get(href) ?? firstHeading(raw) ?? id, characters: text.length });
  }

  const urls: string[] = [];
  const resourceUrl = (base: string) => (href: string): string | null => {
    const path = resolveHref(base, href.split("#")[0] ?? "");
    const bytes = files[path];
    if (bytes === undefined) return null;
    const url = URL.createObjectURL(new Blob([bytes as BlobPart], { type: mediaTypeFor(path) }));
    urls.push(url);
    return url;
  };

  const meta = (tag: string): string | null => {
    const element = Array.from(opf.getElementsByTagName("*")).find((node) => node.localName === tag);
    return element?.textContent?.trim() ?? null;
  };

  return {
    title: meta("title") ?? "Untitled",
    language: meta("language"),
    creator: meta("creator"),
    spine,
    characters: spine.reduce((total, item) => total + item.characters, 0),
    chapter: async (index: number): Promise<Chapter> => {
      const item = spine[index];
      if (item === undefined) throw new Error("There is no such chapter in this book.");
      const raw = TEXT.decode(files[item.href]!);
      return { href: item.href, html: sanitiseDocument(raw, resourceUrl(item.href)), text: stripTags(raw) };
    },
    close: () => {
      for (const url of urls) URL.revokeObjectURL(url);
      urls.length = 0;
    },
  };
}

/** EPUB 3 nav documents and EPUB 2 NCX both map a chapter file to the name a reader should see. */
function tableOfContents(opf: Document, manifest: Map<string, string>, files: Record<string, Uint8Array>,
                         rootPath: string): Map<string, string> {
  const titles = new Map<string, string>();
  const navId = Array.from(opf.getElementsByTagName("item"))
    .find((item) => (item.getAttribute("properties") ?? "").split(/\s+/).includes("nav"))?.getAttribute("id");
  const ncxId = opf.querySelector("spine")?.getAttribute("toc");

  const navPath = navId ? manifest.get(navId) : undefined;
  if (navPath && files[navPath]) {
    const nav = new DOMParser().parseFromString(TEXT.decode(files[navPath]), "text/html");
    for (const anchor of Array.from(nav.getElementsByTagName("a"))) {
      const href = anchor.getAttribute("href");
      const label = anchor.textContent?.trim();
      if (href && label) titles.set(resolveHref(navPath, href.split("#")[0] ?? ""), label);
    }
  }

  const ncxPath = ncxId ? manifest.get(ncxId) : undefined;
  if (ncxPath && files[ncxPath]) {
    const ncx = parse(TEXT.decode(files[ncxPath]));
    for (const point of Array.from(ncx.getElementsByTagName("navPoint"))) {
      const href = point.getElementsByTagName("content")[0]?.getAttribute("src");
      const label = point.getElementsByTagName("text")[0]?.textContent?.trim();
      if (href && label) titles.set(resolveHref(ncxPath, href.split("#")[0] ?? ""), label);
    }
  }
  void rootPath;
  return titles;
}

function firstHeading(html: string): string | null {
  const document_ = new DOMParser().parseFromString(html, "text/html");
  for (const tag of ["h1", "h2", "h3", "title"]) {
    const text = document_.getElementsByTagName(tag)[0]?.textContent?.trim();
    if (text) return text;
  }
  return null;
}

function stripTags(html: string): string {
  const document_ = new DOMParser().parseFromString(html, "text/html");
  for (const tag of ["script", "style"]) {
    for (const element of Array.from(document_.getElementsByTagName(tag))) element.remove();
  }
  return (document_.body?.textContent ?? "").replace(/\s+/g, " ").trim();
}

function mediaTypeFor(path: string): string {
  const extension = path.split(".").pop()?.toLowerCase() ?? "";
  const types: Record<string, string> = {
    png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif", webp: "image/webp",
    svg: "image/svg+xml", css: "text/css", otf: "font/otf", ttf: "font/ttf", woff: "font/woff", woff2: "font/woff2",
  };
  return types[extension] ?? "application/octet-stream";
}
