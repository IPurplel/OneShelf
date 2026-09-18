import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Drawer } from "@/components/Drawer";
import { useI18n } from "@/i18n/i18n";
import { HighlightPane } from "./HighlightPane";
import { useBookMarks } from "./useBookMarks";

type TextItem = { str?: string };
type PdfPage = {
  getViewport: (options: { scale: number }) => { width: number; height: number };
  render: (options: unknown) => { promise: Promise<void> };
  getTextContent: () => Promise<{ items: TextItem[] }>;
};
type PdfDocument = { numPages: number; getPage: (n: number) => Promise<PdfPage> };

/** The text a page carries, as the document itself wrote it — nothing is invented for a scan. */
async function pageText(document_: PdfDocument, page: number): Promise<string> {
  try {
    const content = await (await document_.getPage(page)).getTextContent();
    return content.items.map((item) => item.str ?? "").join("").replace(/\s+/g, " ").trim();
  } catch {
    return "";
  }
}

/**
 * The PDF viewer (Master §26.22, §27, ledger K3).
 *
 * pdf.js renders into a canvas this component owns. Only the canvas layer is rendered — no annotation
 * layer, which is the only place pdf.js can run a document's own scripts — and the document is given no
 * network of its own. An untrusted PDF therefore has no script engine, no session and no privileged
 * application action available to it.
 *
 * Search reads the text layer the document carries; a scan without one is said to carry no text rather
 * than searched with invented content. Bookmarks and highlights are kept with the library (§26.22).
 */
export function PdfView({ unitId, data, workId, onProgress, onLeave, storedPage = null }: {
  unitId: string;
  data: ArrayBuffer | null;
  workId: string;
  onProgress: (fraction: number, locator: unknown) => void;
  onLeave: () => void;
  /** The page the library says this document was left on (§26.15); null resumes nothing. */
  storedPage?: number | null;
}) {
  const { t } = useI18n();
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const [document_, setDocument] = useState<PdfDocument | null>(null);
  const [page, setPage] = useState(1);
  const [text, setText] = useState("");
  const [panel, setPanel] = useState<null | "search" | "highlight" | "marks">(null);
  const [failure, setFailure] = useState<string | null>(null);
  const marks = useBookMarks(unitId);
  const resumed = useRef<string | null>(null);

  useEffect(() => {
    if (data === null) return;
    let live = true;
    void (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).href;
        // pdf.js 5 removed eval from its rendering path, and embedded PDF scripts only ever run in the
        // annotation layer, which this viewer never renders. Auto-fetch and ranged requests are off, so
        // the document cannot drive network activity of its own.
        const task = pdfjs.getDocument({
          data: new Uint8Array(data),
          disableAutoFetch: true,
          disableRange: true,
        });
        const loaded = await task.promise;
        if (live) setDocument(loaded as unknown as PdfDocument);
      } catch (error) {
        if (live) setFailure(error instanceof Error ? error.message : String(error));
      }
    })();
    return () => { live = false; };
  }, [data]);

  useEffect(() => {
    if (document_ === null) return;
    let live = true;
    void (async () => {
      const rendered = await document_.getPage(page);
      if (!live) return;
      const viewport = rendered.getViewport({ scale: 1.5 });
      const target = canvas.current;
      if (target !== null) {
        target.width = viewport.width;
        target.height = viewport.height;
        const context = target.getContext("2d");
        if (context !== null) await rendered.render({ canvasContext: context, viewport, canvas: target }).promise;
      }
      if (!live) return;
      setText(await pageText(document_, page));
      onProgress(page / document_.numPages, { page });
    })();
    return () => { live = false; };
  }, [document_, page, onProgress]);

  useEffect(() => {
    if (document_ === null || storedPage === null || resumed.current === unitId) return;
    resumed.current = unitId;
    setPage(Math.min(Math.max(1, storedPage), document_.numPages));
  }, [document_, storedPage, unitId]);

  const move = useCallback((delta: number) => {
    setPage((current) => {
      if (document_ === null) return current;
      return Math.min(Math.max(1, current + delta), document_.numPages);
    });
  }, [document_]);

  if (failure !== null) {
    return <div className="reader reader--white"><p className="notice notice--problem" role="alert">{failure}</p></div>;
  }

  return (
    <div className="reader reader--dark book">
      <div role="toolbar" aria-label={t("reader.controls")} className="reader__bar reader__bar--top">
        <Link className="reader__button" to={workId ? `/works/${workId}` : "/shelf"} onClick={onLeave}>
          {t("reader.back")}
        </Link>
        <button type="button" className="reader__button" onClick={() => setPanel("search")}>
          {t("pdf.search")}
        </button>
        <button type="button" className="reader__button"
                onClick={() => void marks.addBookmark({ page }, t("pdf.page", { page }))}>
          {t("book.bookmark")}
        </button>
        <button type="button" className="reader__button" onClick={() => setPanel("highlight")}>
          {t("book.highlight")}
        </button>
        <button type="button" className="reader__button" onClick={() => setPanel("marks")}>
          {t("pdf.marks")}
        </button>
      </div>

      <div className="book__pdf">
        <canvas ref={canvas} aria-label={t("book.content")} role="img" />
      </div>

      <div role="toolbar" aria-label={t("reader.progressBar")} className="reader__bar reader__bar--bottom">
        <button type="button" className="reader__button" onClick={() => move(-1)}>{t("pdf.previous")}</button>
        <span role="status">
          {document_ === null ? t("state.loading")
            : t("book.position", { index: page, total: document_.numPages })}
        </span>
        <button type="button" className="reader__button" onClick={() => move(1)}>{t("pdf.next")}</button>
      </div>

      {panel === "search" && document_ !== null && (
        <PdfSearch document_={document_} onClose={() => setPanel(null)}
                   onGo={(target) => { setPage(target); setPanel(null); }} />
      )}

      {panel === "highlight" && (
        text === "" ? (
          <Drawer title={t("book.highlight")} onClose={() => setPanel(null)}>
            <p>{t("pdf.noText")}</p>
          </Drawer>
        ) : (
          <HighlightPane text={text} onClose={() => setPanel(null)}
                         onKeep={(selection) => {
                           void marks.addHighlight({ page, start: selection.start, end: selection.end },
                                                   selection.text);
                           setPanel(null);
                         }} />
        )
      )}

      {panel === "marks" && (
        <Drawer title={t("pdf.marks")} onClose={() => setPanel(null)}>
          <ul className="drawer__units">
            {marks.bookmarks.map((bookmark) => (
              <li key={bookmark.id}>
                <button type="button" className="drawer__unit"
                        onClick={() => { setPage(bookmark.locator.page ?? 1); setPanel(null); }}>
                  <span className="drawer__unitTitle">{bookmark.label}</span>
                </button>
                <button type="button" className="chip" onClick={() => void marks.removeBookmark(bookmark.id)}>
                  {t("book.removeMark")}
                </button>
              </li>
            ))}
            {marks.bookmarks.length === 0 && <li className="shelf__empty">{t("book.noBookmarks")}</li>}
          </ul>
          <ul className="drawer__units">
            {marks.highlights.map((highlight) => (
              <li key={highlight.id}>
                <button type="button" className="drawer__unit"
                        onClick={() => { setPage(highlight.locator.page ?? 1); setPanel(null); }}>
                  <span className="drawer__unitTitle">{highlight.text}</span>
                </button>
                <button type="button" className="chip" onClick={() => void marks.removeHighlight(highlight.id)}>
                  {t("book.removeMark")}
                </button>
              </li>
            ))}
            {marks.highlights.length === 0 && <li className="shelf__empty">{t("book.noHighlights")}</li>}
          </ul>
        </Drawer>
      )}
    </div>
  );
}

function PdfSearch({ document_, onGo, onClose }: {
  document_: PdfDocument;
  onGo: (page: number) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<{ page: number; excerpt: string }[]>([]);
  const [searched, setSearched] = useState(false);
  const pages = useMemo(() => Array.from({ length: document_.numPages }, (_, index) => index + 1), [document_]);

  useEffect(() => {
    const needle = query.trim().toLowerCase();
    if (needle.length < 2) {
      setHits([]);
      setSearched(false);
      return;
    }
    let live = true;
    void (async () => {
      const found: { page: number; excerpt: string }[] = [];
      for (const number of pages) {
        const content = await pageText(document_, number);
        const position = content.toLowerCase().indexOf(needle);
        if (position >= 0) {
          found.push({ page: number, excerpt: content.slice(Math.max(0, position - 40), position + 60) });
        }
      }
      if (!live) return;
      setHits(found);
      setSearched(true);
    })();
    return () => { live = false; };
  }, [document_, pages, query]);

  return (
    <Drawer title={t("pdf.search")} onClose={onClose}>
      <p className="cards__meta">{t("pdf.searchHelp")}</p>
      <input type="search" className="field" aria-label={t("pdf.search")} value={query}
             onChange={(event) => setQuery(event.target.value)} placeholder={t("pdf.search")} />
      {searched && hits.length === 0 && <p className="shelf__empty">{t("pdf.noMatches")}</p>}
      <ul className="drawer__units">
        {hits.map((hit) => (
          <li key={hit.page}>
            <button type="button" className="drawer__unit" onClick={() => onGo(hit.page)}>
              <span className="drawer__unitTitle">{t("pdf.page", { page: hit.page })}</span>
              <span className="drawer__unitState">{hit.excerpt}</span>
            </button>
          </li>
        ))}
      </ul>
    </Drawer>
  );
}
