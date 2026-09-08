# WP-5 — triage of the 183 supplied sources

Probed 2026-09-08 UTC. Two passes: an ordinary anonymous HTTP client
first (which measures the site), then everything that failed or came
back too small re-asked through the app's desync proxy (which measures
whether *this network* was the problem).

**No tier is assigned here.** A tier needs an artifact (T4) or a named
blocking reason (TB), and neither is decided by fetching a homepage.

| Outcome | Count |
|---|---|
| Live — returned real content | **74** |
| Not live — dead, parked, challenged or unreachable | **80** |
| Excluded — account gate or shadow library | **29** |
| **Total** | **183** |

## The headline: the site list is substantially stale

Of 183 supplied hosts, **80 are not live** from here — and 67 of those
do not answer even through the desync bypass, so this is not the ISP
filter. Spot-checked, they are dead in several distinct ways:

- 62 — unreachable via desync too
- 18 — shell only (interstitial or placeholder)

`mangak.com` now serves a HugeDomains **for-sale page**. `mangarose.com`
and `ozulscans.com` redirect into ad networks. Others answer 200 with a
114-byte body. A 200 is not content, and a homepage fetch that only
checks the status code would have called all of these healthy.

## Group D was a hypothesis, and it did not hold

The meta prompt predicted ~32 sites needing zero code — 20 Madara and 12
MangaThemesia. Measured: **one**. `kolnovel.com` is fingerprinted, and by
MangaThemesia rather than the Madara the list predicted. Of the other 31,
most are simply gone; the ones that answer serve Next.js or plain
WordPress, not the themes.

This is the single most important correction in this pass: **WP-6 is
nearly empty, so the coverage cost is adapter work, not configuration.**

## WP-6 queue — fingerprinted, no adapter code needed

| Site | Adapter | Category | Status |
|---|---|---|---|
| www.noor-book.com | books | Books / Digital Library | already T4 |
| www.hindawi.org | books | Books / Digital Library | already a known host |
| 3asq.org | madara | Manga | already T4 |
| dlib.nyu.edu | books | Digital Library | **new candidate** |
| cenele.com | madara | Web Novels | **new candidate** |
| www.rwayat.online | blogger | Novels | **new candidate** |
| kolnovel.com | mangathemesia | Web Novels / Light Novels | **new candidate** |
| infinity896.blogspot.com | blogger | Manga | blog homepage, not a series page |
| royalroad.com | royalroad | Web Novels | already T4 |
| gutenberg.org | gutenberg | Books / Digital Library | already T4 |

Four are genuinely new: `dlib.nyu.edu` (Arabic Collections Online),
`cenele.com`, `www.rwayat.online` and `kolnovel.com`. Two were tested
immediately and **both failed for the same reason** — see below.

## The finding that shapes WP-7: prose sites wearing manga themes

`kolnovel.com` fingerprints as MangaThemesia and the adapter listed
**13,406 chapters** correctly — then failed with *"No page images found"*.
`cenele.com` fingerprints as Madara and found no chapter list at all.

Both are **Arabic web-novel sites running a manga platform's theme**.
A kolnovel chapter page carries **180 `<p>` elements and 0 `<img>`**:

> ساخن 6578 – ساخن بعد رؤيته قادمًا للاستراحة على السرير...

The theme matched; the *content type* did not. Both adapters assume a
chapter is images. The text path they need already exists and is proven
— `prose.py`, `packaging = "text"`, `packager.write_epub`, working today
on Sunovels and Royal Road.

This matters well beyond two sites. The supplied inventory lists ~15
Arabic novel sites and ~20 English web-novel sites, and the natural
shape of the fix is one change to how a chapter's *kind* is decided,
not one adapter per site.

## WP-7 queue — platform clusters among live, unclaimed sites

| Platform | Sites | Note |
|---|---|---|
| unrecognised | 29 | no framework marker; needs individual reading |
| next.js | 12 | a rendering choice, not a platform — these do not share a scraper |
| wordpress | 10 | shared CMS, but the *theme* decides the markup |
| laravel | 8 | backend framework; says nothing about the DOM |
| nuxt | 2 | as next.js |
| drupal | 2 | as wordpress |
| vcomics/astro | 1 | asuracomic.net — check against the existing vcomics adapter |

**These are not adapter-sized clusters.** Next.js, Laravel and WordPress
describe how a site is *built*, not how its chapters are laid out — a
scraper cannot be shared on that basis. Only `vcomics/astro` names real
markup. So the honest read is that the remaining coverage is roughly
one adapter per site or per small family, and the platform-cluster
shortcut the meta prompt hoped for is not available at this scale.

## Excluded (29)

Group A (account, subscription or purchase) and Group B (shadow
libraries), taken from the meta prompt's own lists. Of these,
`comixology.com` and `toomics.com` were confirmed reachable here but are
excluded on the access rule, not on reachability. The genuinely mixed
sites the prompt flags — `tapas.io`, `openlibrary.org`, `bookboon.com` —
are **not** in this count and still need their anonymous tier assessed.

## What this means for the 92-site target

At most **74 of the 183 supplied sites are live and not
excluded**, so 92 verified sites is not reachable from this list: even
if every live site worked perfectly, the ceiling is 74. The realistic
target is the live set minus whatever needs an account behind its
homepage, and each one costs adapter work rather than a config line.
