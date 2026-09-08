# 3asq Madara captures

Captured 2026-09-08 UTC using HTTP through the app's desync proxy and its default
User-Agent; no authenticated browser or account was used.

- `series.html`: GET `https://3asq.org/manga/hunter-x-hunter/`, redirected to
  `https://3asq.online/manga/hunter-x-hunter/`; the canonical link names the latter.
- `chapters.html`: POST `https://3asq.online/manga/hunter-x-hunter/ajax/chapters/`;
  93 chapter entries.
- `reader.html`: GET `https://3asq.online/manga/hunter-x-hunter/01/`; 33 image URLs.

This reader parses, but six source image URLs returned 404 in the real queue.
It is deliberately retained as parsing evidence, not download-success evidence.
The successful artifact used chapter 420, with 16 fully decoded full-size pages;
see `docs/evidence/wp1/asq.json`.
