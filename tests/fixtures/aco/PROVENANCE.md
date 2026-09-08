# Arabic Collections Online capture

Captured 2026-09-08 UTC with an anonymous HTTPS GET; no account, no browser,
no cleared bot check.

- `manifest.json`: GET
  `https://sites.dlib.nyu.edu/viewer/api/presentation/books/aub_aco000056/manifest.json`
  — the IIIF Presentation 3.0 manifest for *Sharḥ dīwān al-Mutanabbī v.3*
  (شرح ديوان المتنبي). 667,253 bytes as served.

**Trimmed, and only in one way:** `items` held 524 canvases, one per scanned
page, and is cut to the first 3. The adapter never reads a canvas — it takes
the whole book from `rendering` — and it only ever counts them, so the trim
changes nothing the code under test looks at while keeping the fixture
reviewable. Everything else is byte-for-byte as served: `label`, `metadata`,
`viewingDirection`, `thumbnail`, `homepage` and both `rendering` entries.

The real 524-page artifact this manifest describes was downloaded and rendered
in full: 262,256,337 bytes, 524 pages. See SOURCES.md.

- `search.html`: GET `https://aco.dlib.nyu.edu/search?q=mutanabbi`; 100,621
  bytes, 30 book links — each hit appearing twice, once romanised and once with
  `?lang=ar` under its Arabic title.
- `search-empty.html`: GET
  `https://aco.dlib.nyu.edu/search?q=zzqvoneshelfnonexistent987654321`; 17,091
  bytes and **zero** `/book/` links. ACO answers an unanswerable query with
  nothing, which is what six other sites in this project do not do.
