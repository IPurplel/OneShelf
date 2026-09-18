/** Shapes the API actually returns; kept close to the backend rather than re-modelled. */
export type Provenance = { source_id: string; listing_key: string; language: string; title: string; url: string | null };

export type ResultWork = {
  work_id: string | null;
  title: string;
  content_type: string | null;
  soft: boolean;
  availability: Record<string, number>;
  provenance: Provenance[];
};

export type LibraryItem = { work_id: string; title: string; cover_url: string | null; fraction: number | null };

export type HeroChoice = {
  reason: "continue_reading" | "pinned" | "cached_discovery";
  title: string;
  work_id: string | null;
  cover_url: string | null;
};

export type HomeResponse = {
  hero: HeroChoice | null;
  continue_reading: LibraryItem[];
  trending: ResultWork[];
  latest: ResultWork[];
  recently_added: LibraryItem[];
};

export type ShelfEntry = {
  work_id: string;
  title: string;
  added_at: string;
  is_favorite: boolean;
  is_pinned: boolean;
  completed_at: string | null;
  releases_since_completion: number;
};

export type ShelfResponse = { view: string; entries: ShelfEntry[] };

export type Notification = {
  id: string;
  dedupe_key: string;
  notification_class: "important" | "informational";
  state: "active" | "resolved";
  seen: boolean;
  count: number;
  title: string;
  summary: string;
  actions: string[];
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type NotificationsResponse = { notifications: Notification[]; needs_attention: number };
