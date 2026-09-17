-- Local search index (Master §6.2). Rebuildable from library records; holds no query history.
CREATE VIRTUAL TABLE search_index USING fts5(
    title,
    normalized,
    loose,
    entity_kind UNINDEXED,
    entity_id UNINDEXED,
    work_id UNINDEXED,
    language UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
