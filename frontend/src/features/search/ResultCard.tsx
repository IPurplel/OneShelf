import { createPortal } from "react-dom";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "@/api/client";
import type { Provenance, ResultWork } from "@/api/types";
import { useResource } from "@/api/useApi";
import { Drawer } from "@/components/Drawer";
import { Icon } from "@/components/Icon";
import { WorkCard } from "@/components/WorkCard";
import { useI18n } from "@/i18n/i18n";
import { languageName } from "@/i18n/language";

type Downloaded = { work_id: string; track_id: string; queued: number; batch_ids: string[] };
type Opened = { listing_id: string; work_id: string; track_id: string; details: string; catalog: string;
                catalog_reason?: string | null };

/**
 * A search or discovery result, always actionable (found on the real UI, 2026-09-21).
 *
 * A live result opens the one concrete listing the person chose, reusing its Work when one exists.
 * It never binds the other listings it was grouped with, and lands on its
 * Work with that source's track selected. When several sources offered it, they choose which; OneShelf never
 * picks a source or language for them because it happened to be listed first.
 */
export function ResultCard({ result, size }: { result: ResultWork; size?: "compact" | "standard" | "detailed" }) {
  const { t, tn, errorText } = useI18n();
  const navigate = useNavigate();
  // "open" picks the listing to open; "download" the one to keep, when several sources offer the result.
  const [choosing, setChoosing] = useState<"open" | "download" | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [queued, setQueued] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const listings = result.provenance.filter((p) => p.source_id !== "local");
  const keepable = listings.filter((p) => p.downloadable);

  const download = async (listing: Provenance) => {
    setChoosing(null);
    setProblem(null);
    setQueued(null);
    setDownloading(true);
    try {
      const done = await api.post<Downloaded>("/api/listings/download", {
        source_id: listing.source_id, listing_key: listing.listing_key, title: listing.title, url: listing.url,
        language: listing.language, content_type: result.content_type, cover_url: listing.cover_url ?? null,
        ...(result.work_id ? { work_id: result.work_id } : {}),
      });
      setQueued(done.queued);
    } catch (error) {
      setProblem(t("search.download.failed", { title: result.title, message: errorText(error) }));
    } finally {
      setDownloading(false);
    }
  };

  const onDownload = () => {
    if (downloading) return;
    if (keepable.length === 1) void download(keepable[0]!);
    else if (keepable.length > 1) setChoosing("download");
  };

  const open = async (listing: Provenance) => {
    setChoosing(null);
    setProblem(null);
    setBusy(true);
    try {
      const opened = await api.post<Opened>("/api/listings/open", {
        source_id: listing.source_id, listing_key: listing.listing_key, title: listing.title, url: listing.url,
        language: listing.language, content_type: result.content_type, cover_url: listing.cover_url ?? null,
        ...(result.work_id ? { work_id: result.work_id } : {}),
        // Land on the Work as soon as the listing is bound: it asks for its own chapters, and its details
        // arrive with `work.changed`. Waiting here kept the card busy for the source's every request.
        defer: true,
      });
      navigate(`/works/${opened.work_id}?track=${encodeURIComponent(opened.track_id)}`,
        opened.catalog === "deferred" ? undefined : {
          state: { catalogAttempt: { trackId: opened.track_id, status: opened.catalog,
                                     reason: opened.catalog_reason ?? null } },
        });
    } catch (error) {
      setProblem(t("search.open.failed", {
        title: result.title, message: errorText(error),
      }));
      setBusy(false);
    }
  };

  const onOpen = () => {
    if (busy) return;
    if (listings.length === 1) void open(listings[0]!);
    else if (listings.length > 1) setChoosing("open");
  };

  if (listings.length === 0) return <WorkCard work={result} size={size} />;

  return (
    <div className="resultcard">
      <WorkCard work={{ ...result, work_id: null, source_count: new Set(listings.map((p) => p.source_id)).size }}
                size={size} onOpen={onOpen} busy={busy} problem={problem}
                status={downloading ? t("search.download.preparing")
                  : queued === null ? null : queued > 0 ? tn("search.download.queued", queued)
                  : t("search.download.none", { title: result.title })} />
      {keepable.length > 0 && (
        // Beside the card, never inside it: the card is itself a button that opens the result.
        <button type="button" className="resultcard__download" onClick={onDownload} disabled={downloading}
                aria-busy={downloading || undefined} aria-label={t("search.download.aria", { title: result.title })}
                title={t("search.download.action")}>
          {/* The icon turns to a check once the download is queued: the tap was heard, and it worked. */}
          <span className="resultcard__icon" key={queued !== null && queued > 0 ? "done" : "idle"}>
            <Icon name={queued !== null && queued > 0 ? "check" : "downloads"} size={18} />
          </span>
        </button>
      )}
      {choosing !== null && createPortal(
        <Drawer title={t(choosing === "download" ? "search.download.choose" : "search.open.choose", { title: result.title })}
                onClose={() => setChoosing(null)}>
          <SourceChoice listings={choosing === "download" ? keepable : listings}
                        help={choosing === "download" ? t("search.download.help") : undefined}
                        onChoose={(listing) => void (choosing === "download" ? download(listing) : open(listing))} />
        </Drawer>, document.body
      )}
    </div>
  );
}

function SourceChoice({ listings, onChoose, help }: {
  listings: Provenance[]; onChoose: (listing: Provenance) => void; help?: string;
}) {
  const { t, language } = useI18n();
  const { data } = useResource<{ sources: { id: string; name: string }[] }>("/api/sources");
  const names = new Map((data?.sources ?? []).map((source) => [source.id, source.name]));
  // Editions from one source can share a title exactly; their own ids are then what tells them apart.
  const seen = new Map<string, number>();
  for (const listing of listings) {
    const key = `${listing.source_id}\u0000${listing.title.toLowerCase()}`;
    seen.set(key, (seen.get(key) ?? 0) + 1);
  }
  const label = (listing: Provenance) =>
    (seen.get(`${listing.source_id}\u0000${listing.title.toLowerCase()}`) ?? 0) > 1
      ? `${listing.title} · #${listing.listing_key.slice(0, 24)}` : listing.title;
  return (
    <>
      <p className="cards__meta">{help ?? t("search.open.help")}</p>
      <ul className="choice">
        {listings.map((listing) => (
          <li key={`${listing.source_id}:${listing.listing_key}:${listing.language}`}>
            <button type="button" className="button choice__option" onClick={() => onChoose(listing)}>
              <span><bdi>{names.get(listing.source_id) ?? listing.source_id.replace(/^oneshelf\./, "")}</bdi> · {languageName(listing.language, language)}</span>
              {/* The listing's own title: how two editions from one source are told apart. */}
              <span className="choice__title" dir="auto">{label(listing)}</span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
