import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { useI18n } from "@/i18n/i18n";

/**
 * The PDF viewer (Master §26.22, §27, ledger K3).
 *
 * pdf.js renders into a canvas this component owns. Only the canvas layer is rendered — no annotation
 * layer, which is the only place pdf.js can run a document's own scripts — and the document is given no
 * network of its own. An untrusted PDF therefore has no script engine, no session and no privileged
 * application action available to it.
 */
export function PdfView({ unitId, data, workId, onProgress, onLeave }: {
  unitId: string;
  data: ArrayBuffer | null;
  workId: string;
  onProgress: (fraction: number, locator: unknown) => void;
  onLeave: () => void;
}) {
  const { t } = useI18n();
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const [document_, setDocument] = useState<{ numPages: number; getPage: (n: number) => Promise<unknown> } | null>(null);
  const [page, setPage] = useState(1);
  const [failure, setFailure] = useState<string | null>(null);

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
        if (live) setDocument(loaded as unknown as { numPages: number; getPage: (n: number) => Promise<unknown> });
      } catch (error) {
        if (live) setFailure(error instanceof Error ? error.message : String(error));
      }
    })();
    return () => { live = false; };
  }, [data]);

  useEffect(() => {
    if (document_ === null || canvas.current === null) return;
    let live = true;
    void (async () => {
      const rendered = await document_.getPage(page) as {
        getViewport: (options: { scale: number }) => { width: number; height: number };
        render: (options: unknown) => { promise: Promise<void> };
      };
      const viewport = rendered.getViewport({ scale: 1.5 });
      const target = canvas.current;
      if (!live || target === null) return;
      target.width = viewport.width;
      target.height = viewport.height;
      const context = target.getContext("2d");
      if (context === null) return;
      await rendered.render({ canvasContext: context, viewport, canvas: target }).promise;
      onProgress(page / document_.numPages, { page });
    })();
    return () => { live = false; };
  }, [document_, page, onProgress]);

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
        <span className="reader__unit">{unitId}</span>
      </div>
      <div className="book__pdf">
        <canvas ref={canvas} aria-label={t("book.content")} role="img" />
      </div>
      <div role="toolbar" aria-label={t("reader.progressBar")} className="reader__bar reader__bar--bottom">
        <button type="button" className="reader__button" onClick={() => move(-1)}>{t("book.previous")}</button>
        <span role="status">
          {document_ === null ? t("state.loading")
            : t("book.position", { index: page, total: document_.numPages })}
        </span>
        <button type="button" className="reader__button" onClick={() => move(1)}>{t("book.next")}</button>
      </div>
    </div>
  );
}
