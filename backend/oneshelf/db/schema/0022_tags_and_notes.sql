-- Tags: user-defined labels on works.
CREATE TABLE tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE work_tags (
    work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (work_id, tag_id)
);

-- Smart collections: auto-populated by filter rules.
CREATE TABLE collections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    is_smart INTEGER NOT NULL DEFAULT 0 CHECK (is_smart IN (0, 1)),
    filter_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE collection_works (
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    PRIMARY KEY (collection_id, work_id)
);

-- Personal notes and ratings on works.
CREATE TABLE work_notes (
    work_id TEXT PRIMARY KEY REFERENCES works(id) ON DELETE CASCADE,
    rating INTEGER CHECK (rating IS NULL OR (rating >= 1 AND rating <= 10)),
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
