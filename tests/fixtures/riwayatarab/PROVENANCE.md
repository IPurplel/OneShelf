# RiwayatArab captures

Captured 2026-09-08 UTC, anonymous; no account, no cleared bot check. The
novel, chapter-list and chapter pages came over plain HTTP through the app's
own path. The two search pages are **rendered DOM**, because that page is the
one thing on this site built client-side.

- `novel.html`: GET `https://riwayatarab.com/novel/demonic-emperor`; 138,123
  bytes. Server-rendered: title in `<h1>`, the first twenty chapters, and the
  link reading *"عرض جميع الفصول (1344)"* that advertises the total.
- `chapters-page1.html`: GET `.../novel/demonic-emperor/chapters`; 151,022
  bytes, chapters **1-50**. Pagination is one-based and non-overlapping —
  `?page=27` is 1301-1344, and 26x50+44 = 1344, the advertised count.
- `chapter1.html`: GET `.../novel/demonic-emperor/chapter/1`; 79,318 bytes.
  `div.chapter-content` holds one `<div>` and **232 `<br>`**, ~8,000 characters.
- `search.html`: **rendered** DOM of `/search?q=الشيطاني`; 107,165 chars.
  Over plain HTTP the same URL returns 25 KB whose `<title>` is *"نتائج البحث
  عن الشيطاني"* and which contains **zero** result links.
- `search-empty.html`: **rendered** DOM of the sentinel query; 26,853 chars and
  no result links — the selector never appears, which is the honest answer.

Verified live: 1,344 chapters resolved, matching the advertised count exactly;
chapter 1 downloaded as a 6,607-byte EPUB rendering to 7 pages.
