import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "@/api/client";
import type { Provenance, ResultWork } from "@/api/types";
import { useResource } from "@/api/useApi";
import { Drawer } from "@/components/Drawer";
import { WorkCard } from "@/components/WorkCard";
import { useI18n } from "@/i18n/i18n";
import { languageName } from "@/i18n/language";

type Opened = { listing_id: string; work_id: string; track_id: string; details: string; catalog: string };

/**
 * A search or discovery result, always actionable (found on the real UI, 2026-09-21).
 *
 * A result that already has a Work links to it. One that does not is a button: opening it binds the one
 * concrete listing the person chose — never the others it was grouped with for display — and lands on its
 * Work with that source's track selected. When several sources offered it, they choose which; OneShelf never
 * picks a source or language for them because it happened to be listed first.
 */
export function ResultCard({ result, size }: { result: ResultWork; size?: "compact" | "standard" | "detailed" }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [choosing, setChoosing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  if (result.work_id) return <WorkCard work={result} size={size} />;

  const listings = result.provenance.filter((p) => p.source_id !== "local");

  const open = async (listing: Provenance) => {
    setChoosing(false);
    setProblem(null);
    setBusy(true);
    try {
      const opened = await api.post<Opened>("/api/listings/open", {
        source_id: listing.source_id, listing_key: listing.listing_key, title: listing.title, url: listing.url,
        language: listing.language, content_type: result.content_type, cover_url: listing.cover_url ?? null,
      });
      navigate(`/works/${opened.work_id}?track=${encodeURIComponent(opened.track_id)}`);
    } catch (error) {
      setProblem(t("search.open.failed", {
        title: result.title, message: error instanceof ApiError ? error.message : t("state.offline"),
      }));
      setBusy(false);
    }
  };

  const onOpen = () => {
    if (busy) return;
    if (listings.length === 1) void open(listings[0]!);
    else if (listings.length > 1) setChoosing(true);
  };

  return (
    <div className="resultcard">
      <WorkCard work={result} size={size} onOpen={listings.length > 0 ? onOpen : undefined} busy={busy} />
      {problem !== null && <p className="notice notice--problem resultcard__problem" role="alert">{problem}</p>}
      {choosing && (
        <Drawer title={t("search.open.choose", { title: result.title })} onClose={() => setChoosing(false)}>
          <SourceChoice listings={listings} onChoose={(listing) => void open(listing)} />
        </Drawer>
      )}
    </div>
  );
}

function SourceChoice({ listings, onChoose }: { listings: Provenance[]; onChoose: (listing: Provenance) => void }) {
  const { t } = useI18n();
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
      <p className="cards__meta">{t("search.open.help")}</p>
      <ul className="choice">
        {listings.map((listing) => (
          <li key={`${listing.source_id}:${listing.listing_key}`}>
            <button type="button" className="button choice__option" onClick={() => onChoose(listing)}>
              <span>{`${names.get(listing.source_id) ?? listing.source_id.replace(/^oneshelf\./, "")} · ${languageName(listing.language)}`}</span>
              {/* The listing's own title: how two editions from one source are told apart. */}
              <span className="choice__title">{label(listing)}</span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
