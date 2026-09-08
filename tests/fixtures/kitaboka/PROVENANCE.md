# Kitaboka captures

Captured 2026-09-08 UTC with plain anonymous HTTP GETs (`curl -L`); no account,
no browser session, no cleared bot check. Sizes are the exact response bodies.

- `search.html`: GET `https://kitaboka.com/books?search=رواية`; 227,374 bytes,
  37 unique `/books/<slug>` links, every title carrying the query word.
- `negative.html`: GET
  `https://kitaboka.com/books?search=zzqvoneshelfnonexistent987654321`;
  202,772 bytes, **27 unique book links** — the catalogue, overlapping the real
  query's results. Kitaboka is the sixth site recorded here that answers an
  unanswerable query with something that merely looks like results.
- `book.html`: GET `https://kitaboka.com/books/hky-zhr` (رواية حكاية زهرة);
  140,916 bytes, one PDF at
  `https://kitaboka.com/storage/book_files/01M00NDG35TDV35A6BTSMBYJH0.pdf`.

## Why these replaced hand-written fixtures

The tests here were previously built from markup written to satisfy the code
under test, and they encoded the alias **backwards**: they asserted that
kitaboka.com resolves to norkitab.com. Live, `norkitab.com` answers 976 bytes of
HTML 4 frameset whose only content is `<frame src="…kitaboka.com/books">`, so
the adapter fetched an empty document and the site returned nothing for every
query — invisible to a test suite whose fixtures agreed with the mistake.
