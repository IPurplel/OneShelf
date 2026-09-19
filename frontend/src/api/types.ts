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

export type LibraryItem = {
  work_id: string;
  title: string;
  cover_url: string | null;
  fraction: number | null;
  content_type?: string | null;
};

export type HeroChoice = {
  reason: "continue_reading" | "pinned" | "cached_discovery";
  title: string;
  work_id: string | null;
  cover_url: string | null;
  description?: string | null;
  content_type?: string | null;
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

export type Track = {
  id: string;
  source_id: string;
  language: string;
  kind: "source" | "local";
  availability: string;
  unit_count: number;
};

export type Unit = {
  id: string;
  title: string | null;
  number: string | null;
  unit_type: string;
  volume: string | null;
  order: number;
  release_date: string | null;
  availability: string;
  url: string | null;
  downloaded: boolean;
  formats: string[];
  read_state: "unread" | "partial" | "read";
  fraction: number;
  read_at: string | null;
  /** §26.19, §26.21: whether the local copy is sound, so the reader can offer repair honestly. */
  integrity: "ok" | "corrupt" | "missing_local_file" | "unknown" | "none";
  /** §26.12: new since the last acknowledged release, from Follow's own record. */
  is_new: boolean;
};

export type WorkDetails = {
  work: {
    id: string;
    title: string;
    original_title: string | null;
    creator: string | null;
    description: string | null;
    content_type: string | null;
    content_type_source: string;
    aliases: string[];
  };
  shelf: { on_shelf: boolean; favorite: boolean; pinned: boolean; completed: boolean };
  follow: {
    following: boolean;
    preferred_source_id: string | null;
    track_id: string | null;
    language: string | null;
    last_successful_at: string | null;
  };
  tracks: Track[];
  selected_track_id: string | null;
  units: Unit[];
  continue_unit_id: string | null;
};
