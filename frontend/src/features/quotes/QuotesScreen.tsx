import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { LoadingState } from "@/components/LoadingState";
import { useI18n } from "@/i18n/i18n";
import { readerLink } from "@/features/reader/links";
import { directionFromText } from "@/features/reader/epub";
import { shareQuoteImage } from "./quoteImage";

export type Quote = {
  id: string; text: string; colour: string; created_at: string; unit_id: string; unit_title: string | null;
  work_id: string; work_title: string; cover_url: string | null;
};

/**
 * Quotes: every sentence you highlighted, in every book, newest first. Each one says where it came from and
 * opens the reader there; it can be copied with its source, saved as an image to share, or let go.
 */
export function QuotesScreen() {
  const { t, language, errorText } = useI18n();
  const { data, error, reload } = useResource<{ highlights: Quote[] }>("/api/highlights");
  const [book, setBook] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  if (error !== null) return <section className="screen"><p className="notice notice--problem" role="alert">{error}</p></section>;
  if (data === null) return <section className="screen"><LoadingState /></section>;

  const books = Array.from(new Map(data.highlights.map((q) => [q.work_id, q.work_title])).entries());
  const shown = book === null ? data.highlights : data.highlights.filter((q) => q.work_id === book);
  const dates = new Intl.DateTimeFormat(language, { dateStyle: "medium" });

  const copy = async (quote: Quote) => {
    try {
      await navigator.clipboard.writeText(`“${quote.text}”\n— ${quote.work_title}`);
      setNotice(t("quotes.copied"));
    } catch (failure) {
      setNotice(errorText(failure));
    }
  };
  const remove = async (quote: Quote) => {
    try {
      await api.delete(`/api/reader/highlights/${quote.id}`);
    } catch (failure) {
      setNotice(errorText(failure));
    } finally {
      reload();
    }
  };

  return (
    <section className="screen quotes">
      <h1 className="screen__title">{t("quotes.title")}</h1>
      <p className="screen__subtitle">{t("quotes.subtitle")}</p>
      {notice !== null && <p className="notice" role="status">{notice}</p>}
      {data.highlights.length === 0 && (
        <div className="empty"><p className="empty__body">{t("quotes.empty")}</p></div>
      )}
      {books.length > 1 && (
        <div className="quotes__books" role="group" aria-label={t("quotes.books")}>
          <button type="button" className="chip" aria-pressed={book === null} onClick={() => setBook(null)}>
            {t("quotes.allBooks")} · {data.highlights.length}
          </button>
          {books.map(([id, title]) => (
            <button key={id} type="button" className="chip" aria-pressed={book === id}
                    onClick={() => setBook(book === id ? null : id)}>
              <bdi>{title}</bdi> · {data.highlights.filter((q) => q.work_id === id).length}
            </button>
          ))}
        </div>
      )}
      <div className="quotes__list">
        {shown.map((quote) => (
          <article key={quote.id} className={`quote quote--${quote.colour}`}>
            <blockquote className="quote__text" dir={directionFromText(quote.text) ?? "auto"}>{quote.text}</blockquote>
            <p className="quote__source">
              <Link to={readerLink(quote.unit_id, quote.work_id)}><bdi>{quote.work_title}</bdi></Link>
              {quote.unit_title && quote.unit_title !== quote.work_title && <> · <bdi>{quote.unit_title}</bdi></>}
              {" · "}<time dateTime={quote.created_at}>{dates.format(new Date(quote.created_at))}</time>
            </p>
            <div className="quote__actions">
              <button type="button" className="chip" onClick={() => void copy(quote)}>{t("quotes.copy")}</button>
              <button type="button" className="chip"
                      onClick={() => void shareQuoteImage(quote, t("app.name")).catch(() => setNotice(t("quotes.imageFailed")))}>
                {t("quotes.share")}
              </button>
              <button type="button" className="chip chip--danger" onClick={() => void remove(quote)}>{t("quotes.delete")}</button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
