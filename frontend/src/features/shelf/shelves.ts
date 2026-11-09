/** Your own shelves, as the library lists them (`GET /api/collections`). */
export type ShelfWork = { work_id: string; title: string; content_type: string | null; cover_url: string | null };
export type Collection = { id: string; name: string; work_count: number; works: ShelfWork[] };
