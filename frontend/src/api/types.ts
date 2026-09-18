/** Shapes the API actually returns; kept close to the backend rather than re-modelled. */
export type Notification = {
  id: string;
  notification_class: "important" | "informational";
  dedupe_key: string;
  title: string;
  summary: string;
  actions: string[];
  state: "active" | "resolved";
  seen_at: string | null;
  created_at: string;
  count: number;
};

export type NotificationsResponse = {
  notifications: Notification[];
  unseen: number;
  attention: number;
};

export type ShelfEntry = {
  work_id: string;
  title: string;
  content_type: string | null;
  cover_url: string | null;
  favorite: boolean;
  pinned: boolean;
  completed: boolean;
  progress: { fraction: number; unit_id: string | null; unit_title: string | null } | null;
  languages: string[];
  source_count: number;
};

export type HomeResponse = {
  hero: (ShelfEntry & { reason: string }) | null;
  continue_reading: ShelfEntry[];
  trending: ShelfEntry[];
  latest: ShelfEntry[];
  recently_added: ShelfEntry[];
};
