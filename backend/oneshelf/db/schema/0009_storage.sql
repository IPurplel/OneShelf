-- Resumable storage migrations (Master §24.8). Old storage is never deleted automatically.
CREATE TABLE storage_migrations (
    id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES storage_roots(id),
    source_path TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('planned', 'copying', 'verifying', 'switched', 'completed', 'failed',
                                         'old_copy_removed')),
    files INTEGER NOT NULL DEFAULT 0,
    bytes INTEGER NOT NULL DEFAULT 0,
    copied INTEGER NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE storage_migration_files (
    migration_id TEXT NOT NULL REFERENCES storage_migrations(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    sha256 TEXT,
    size INTEGER,
    state TEXT NOT NULL CHECK (state IN ('pending', 'copied', 'verified')),
    PRIMARY KEY (migration_id, relative_path)
);
