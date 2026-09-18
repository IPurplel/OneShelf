import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "@/api/client";
import { useI18n } from "@/i18n/i18n";
import { Drawer } from "@/components/Drawer";
import { openEpub } from "./epub";
import type { Epub } from "./epub";
import { HighlightPane } from "./HighlightPane";
import { PdfView } from "./PdfView";
import { useBookMarks } from "./useBookMarks";
import { useProgress } from "./useProgress";

/**
 * The Book Reader (Master §26.22) for EPUB and PDF.
 *
 * Untrusted document content never enters the application origin (§27, ledger K3): EPUB chapters are
 * sanitised and rendered inside a frame with an empty sandbox — no scripts, no same-origin — under its
 * own restrictive CSP, and PDFs are rendered by pdf.js with eval and PDF scripting disabled. Progress is
 * logical (chapter share for EPUB, page for PDF); there is no invented fixed page count.
 */
export function BookReader({ unitId, format, workId }: { unitId: string; format: "epub" | "pdf"; workId: string }) {
  const { t, direction } = useI18n();
  const [bytes, setBytes] = useState<ArrayBuffer | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [book, setBook] = useState<Epub | null>(null);
  const [chapterIndex, setChapterIndex] = useState(0);
  const [html, setHtml] = useState("");
  const [panel, setPanel] = useState<null | "contents" | "search" | "highlight">(null);
  const [chapterText, setChapterText] = useState("");
  const marks = useBookMarks(unitId);
  const { record, flush, stored } = useProgress(unitId);
  const resumed = useRef<string | null>(null);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const response = await fetch(`/api/reader/units/${unitId}/file`, { credentials: "same-origin" });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new ApiError(response.status, payload?.error?.code ?? "FILE_NOT_AVAILABLE",
                             payload?.error?.message ?? "This file is not on this device.");
        }
        const data = await response.arrayBuffer();
        if (live) setBytes(data);
      } catch (error) {
        if (live) setFailure(error instanceof ApiError ? error.message : t("state.offline"));
      }
    })();
    return () => { live = false; };
  }, [unitId, t]);

  useEffect(() => {
    if (bytes === null || format !== "epub") return;
    let live = true;
    void (async () => {
      try {
        const opened = await openEpub(bytes);
        if (live) setBook(opened);
      } catch (error) {
        if (live) setFailure(error instanceof Error ? error.message : String(error));
      }
    })();
    return () => { live = false; };
  }, [bytes, format]);

  useEffect(() => () => book?.close(), [book]);

  useEffect(() => {
    if (book === null) return;
    let live = true;
    void (async () => {
      const chapter = await book.chapter(chapterIndex);
      if (!live) return;
      setHtml(frameDocument(chapter.html, direction));
      setChapterText(chapter.text);
      const read = book.spine.slice(0, chapterIndex + 1).reduce((total, item) => total + item.characters, 0);
      record(book.characters === 0 ? 0 : read / book.characters, { chapter: chapterIndex });
    })();
    return () => { live = false; };
  }, [book, chapterIndex, direction, record]);

  /** Resume the chapter this book was left on (§26.15); reading the position writes nothing. */
  useEffect(() => {
    if (book === null || stored === null || resumed.current === unitId) return;
    resumed.current = unitId;
    const locator = stored.locator as { chapter?: number } | null;
    if (typeof locator?.chapter !== "number") return;
    setChapterIndex(Math.min(Math.max(0, locator.chapter), book.spine.length - 1));
  }, [book, stored, unitId]);

  const move = useCallback((delta: number) => {
    setChapterIndex((current) => {
      const target = current + delta;
      if (book === null || target < 0 || target >= book.spine.length) return current;
      return target;
    });
  }, [book]);

  if (failure !== null) {
    return (
      <div className="reader reader--white">
        <p className="notice notice--problem" role="alert">{failure}</p>
        <Link className="button" to={workId ? `/works/${workId}` : "/shelf"}>{t("reader.backToWork")}</Link>
      </div>
    );
  }

  if (format === "pdf") {
    return <PdfView unitId={unitId} data={bytes} workId={workId} onProgress={record} onLeave={flush}
                    storedPage={(stored?.locator as { page?: number } | null)?.page ?? null} />;
  }

  return (
    <div className="reader reader--white book">
      <div role="toolbar" aria-label={t("reader.controls")} className="reader__bar reader__bar--top">
        <Link className="reader__button" to={workId ? `/works/${workId}` : "/shelf"} onClick={flush}>
          {t("reader.back")}
        </Link>
        <span className="reader__title">{book?.title ?? ""}</span>
        <button type="button" className="reader__button" onClick={() => setPanel("contents")}>
          {t("reader.contents")}
        </button>
        <button type="button" className="reader__button" onClick={() => setPanel("search")}>
          {t("book.search")}
        </button>
        <button type="button" className="reader__button"
                onClick={() => void marks.addBookmark({ chapter: chapterIndex },
                                                      chapterLabel(book, chapterIndex))}>
          {t("book.bookmark")}
        </button>
        <button type="button" className="reader__button" onClick={() => setPanel("highlight")}>
          {t("book.highlight")}
        </button>
      </div>

      <iframe className="book__frame" title={t("book.content")} sandbox="" srcDoc={html} />

      <div role="toolbar" aria-label={t("reader.progressBar")} className="reader__bar reader__bar--bottom">
        <button type="button" className="reader__button" onClick={() => move(-1)}>{t("book.previous")}</button>
        <span role="status">
          {book === null ? t("state.loading")
            : t("book.position", { index: chapterIndex + 1, total: book.spine.length })}
        </span>
        <button type="button" className="reader__button" onClick={() => move(1)}>{t("book.next")}</button>
      </div>

      {panel === "contents" && (
        <BookContents book={book} current={chapterIndex} marks={marks}
                      onGo={(index) => { setChapterIndex(index); setPanel(null); }}
                      onClose={() => setPanel(null)} />
      )}
      {panel === "search" && (
        <BookSearch book={book} onGo={(index) => { setChapterIndex(index); setPanel(null); }}
                    onClose={() => setPanel(null)} />
      )}
      {panel === "highlight" && (
        <HighlightPane text={chapterText} onClose={() => setPanel(null)}
                       onKeep={(selection) => {
                         void marks.addHighlight({ chapter: chapterIndex, start: selection.start,
                                                   end: selection.end }, selection.text);
                         setPanel(null);
                       }} />
      )}
    </div>
  );
}

function chapterLabel(book: Epub | null, index: number): string {
  return book?.spine[index]?.title ?? `Chapter ${index + 1}`;
}

/**
 * The document handed to the sandboxed frame. It carries its own CSP so that even if something survived
 * sanitisation it can neither execute nor fetch: only inline styles and the blob resources we made.
 */
function frameDocument(body: string, direction: "ltr" | "rtl"): string {
  const csp = "default-src 'none'; img-src blob: data:; style-src 'unsafe-inline'; font-src blob:;";
  return `<!doctype html><html dir="${direction}"><head>
    <meta charset="utf-8">
    <meta http-equiv="Content-Security-Policy" content="${csp}">
    <style>
      :root { color-scheme: light; }
      body { margin: 0 auto; padding: 4vh 6vw; max-width: 42rem; font: 18px/1.7 Georgia, "Noto Naskh Arabic", serif;
             color: #1c1b18; background: #fffdf8; }
      img { max-width: 100%; height: auto; }
      h1, h2, h3 { line-height: 1.3; }
    </style></head><body>${body}</body></html>`;
}

function BookContents({ book, current, marks, onGo, onClose }: {
  book: Epub | null;
  current: number;
  marks: ReturnType<typeof useBookMarks>;
  onGo: (index: number) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"toc" | "bookmarks" | "highlights">("toc");

  return (
    <Drawer title={t("reader.contents")} onClose={onClose}>
      <div className="drawer__filters" role="tablist" aria-label={t("reader.contents")}>
        {(["toc", "bookmarks", "highlights"] as const).map((candidate) => (
          <button key={candidate} type="button" role="tab" className="chip" aria-selected={tab === candidate}
                  onClick={() => setTab(candidate)}>
            {t(`book.tab.${candidate}` as const)}
          </button>
        ))}
      </div>

      {tab === "toc" && (
        <ul className="drawer__units">
          {(book?.spine ?? []).map((item, index) => (
            <li key={item.href}>
              <button type="button" className={index === current ? "drawer__unit is-current" : "drawer__unit"}
                      onClick={() => onGo(index)}>
                <span className="drawer__unitTitle">{item.title}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {tab === "bookmarks" && (
        <ul className="drawer__units">
          {marks.bookmarks.map((bookmark) => (
            <li key={bookmark.id}>
              <button type="button" className="drawer__unit" onClick={() => onGo(bookmark.locator.chapter ?? 0)}>
                <span className="drawer__unitTitle">{bookmark.label}</span>
              </button>
              <button type="button" className="chip" onClick={() => void marks.removeBookmark(bookmark.id)}>
                {t("book.removeMark")}
              </button>
            </li>
          ))}
          {marks.bookmarks.length === 0 && <li className="shelf__empty">{t("book.noBookmarks")}</li>}
        </ul>
      )}

      {tab === "highlights" && (
        <ul className="drawer__units">
          {marks.highlights.map((highlight) => (
            <li key={highlight.id}>
              <button type="button" className="drawer__unit" onClick={() => onGo(highlight.locator.chapter ?? 0)}>
                <span className="drawer__unitTitle">{highlight.text}</span>
              </button>
              <button type="button" className="chip" onClick={() => void marks.removeHighlight(highlight.id)}>
                {t("book.removeMark")}
              </button>
            </li>
          ))}
          {marks.highlights.length === 0 && <li className="shelf__empty">{t("book.noHighlights")}</li>}
        </ul>
      )}
    </Drawer>
  );
}

function BookSearch({ book, onGo, onClose }: {
  book: Epub | null;
  onGo: (index: number) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<{ index: number; label: string; excerpt: string }[]>([]);

  const spine = useMemo(() => book?.spine ?? [], [book]);

  useEffect(() => {
    if (book === null || query.trim().length < 2) {
      setHits([]);
      return;
    }
    let live = true;
    void (async () => {
      const found: { index: number; label: string; excerpt: string }[] = [];
      for (let index = 0; index < spine.length; index += 1) {
        const chapter = await book.chapter(index);
        const position = chapter.text.toLowerCase().indexOf(query.trim().toLowerCase());
        if (position >= 0) {
          found.push({
            index,
            label: spine[index]!.title,
            excerpt: chapter.text.slice(Math.max(0, position - 40), position + 60),
          });
        }
      }
      if (live) setHits(found);
    })();
    return () => { live = false; };
  }, [book, query, spine]);

  return (
    <Drawer title={t("book.search")} onClose={onClose}>
      <input type="search" className="field" aria-label={t("book.search")} value={query}
             onChange={(event) => setQuery(event.target.value)} placeholder={t("book.search")} />
      <ul className="drawer__units">
        {hits.map((hit) => (
          <li key={hit.index}>
            <button type="button" className="drawer__unit" onClick={() => onGo(hit.index)}>
              <span className="drawer__unitTitle">{hit.label}</span>
              <span className="drawer__unitState">{hit.excerpt}</span>
            </button>
          </li>
        ))}
      </ul>
    </Drawer>
  );
}
