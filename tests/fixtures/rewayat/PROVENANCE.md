# Rewayat Club captures

Captured 2026-09-08 UTC through the app's own HTTP path (desync proxy, default
User-Agent); no account, no browser, no cleared bot check. Byte-for-byte as
served.

- `novel.html`: GET `https://rewayat.club/novel/cleaver-of-sin`; 116,267 bytes.
  Shows the **newest 24 chapters only**, of a serial that runs to 955, with no
  pagination control and no "all chapters" link. Its `__NUXT__` payload holds
  the novel record — Arabic title, English title, description — and **not** the
  chapter list.
- `chapter1.html`: GET `https://rewayat.club/novel/cleaver-of-sin/1`; 118,722
  bytes. Its payload carries `allChapters`: **954 literal entries spanning
  2-955**. The entry for chapter 1 — the chapter this page *is* — is built by
  variable assignment (`i.text=e`) rather than written as a literal, which is
  why the adapter adds the fetched chapter back explicitly to reach a
  contiguous 1-955.

The payload is minified JavaScript, not JSON: `value` is a reference to a
single-letter variable assigned earlier in the same function, so chapter
numbers are read from the literal `text` instead.

Verified live: 955 chapters resolved, and chapter 1 downloaded as a 6,257-byte
EPUB rendering to 5 pages.
- `chapter-newest.html`: GET `https://rewayat.club/novel/cleaver-of-sin/955`;
  109,748 bytes. The chapter the adapter actually opens, since the novel page's
  newest link is the one it is guaranteed to have. Its `allChapters` lists
  **1-954 and omits 955** — the same "no literal entry for the chapter you are
  on" behaviour, seen from the other end. Kept precisely because it proves the
  rule is about the *current* chapter, not about chapter 1.
- `search.html`: GET `https://rewayat.club/library?search=ساطور`; 42,545 bytes,
  one novel link. Note the endpoint: `/search?q=` renders a page that *mentions*
  the query and links nothing; the library's filter is what answers.
- `search-empty.html`: GET
  `https://rewayat.club/library?search=zzqvoneshelfnonexistent987654321`;
  39,028 bytes and **zero** novel links.
