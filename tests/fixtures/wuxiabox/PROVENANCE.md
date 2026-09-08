# WuxiaBox captures

Captured 2026-09-08 UTC through the app's own HTTP path (desync proxy, default
User-Agent); no account, no browser, no cleared bot check. Sizes are the exact
response bodies.

- `chapters-tab.html`: GET
  `https://wuxiabox.com/novel/absolute-resonance.html?tab=chapters`; 47,553
  bytes. Recounted from the saved `ul.chapter-list` on 2026-09-08: **100 links
  total, representing 90 distinct chapters (1-90)**. Ten links are zero-padded
  duplicates (`…_0046.html` … `…_0055.html`) of chapters already listed
  unpadded. The previous description incorrectly said 100 distinct chapters
  plus duplicates. That is the case the adapter's number-keyed de-duplication
  exists for.
- `chapters-page1.html`: GET
  `https://wuxiabox.com/e/extend/fy.php?page=1&wjm=absolute-resonance`; 31,487
  bytes, chapters **91-190** — the page number is zero-based *and* the stride
  is 90 against a page size of 100 in the recorded later pagination. These
  first two saved pages contribute **190 distinct chapters together**; the
  first page's duplicates mean they do not themselves overlap in chapter number.
- `chapter.html`: GET `https://wuxiabox.com/novel/absolute-resonance_1.html`;
  36,208 bytes. `div.chapter-content` holds **one `<p>` and 234 `<br>`**,
  19,478 characters of prose.

Measured on the live novel: 1,333 listed links, **1,216 distinct chapters**.
Without de-duplicating on the chapter number, 117 chapters would have been
downloaded and packaged twice.
