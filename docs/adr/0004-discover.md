# ADR 0004 — Discover: a source's own lists, read a page at a time

Status: accepted.

People want something to read without knowing its name. OneShelf has no catalogue of its own and must not
invent one, so Discover shows only what a source itself publishes and says where every suggestion came from.

**Feeds are recipe capabilities.** A source that can be browsed declares `latest` and/or `trending`, list
capabilities with the same fields as `search` (shown to people as "Latest" and "Popular"). Nothing is ranked,
scored or merged across sources: the order is the source's. A feed result is grouped into Works exactly as a
search result is (INV-27), and says when the Work is already on the shelf.

**One page per request.** `RecipeRuntime.run(..., pages=(first, count))` reads a window of a list instead of
the recipe's whole `max_pages`. A window may start no deeper than page 200 and read no more than the recipe
allows; a list paged by `next_link`, or not paged at all, can only be read from its first page. Discover asks
for one page per "Load more" and stops at page 50, an empty page, or a list that says it is complete.

**Cached, never stale-only.** A page read within 6 hours is shown again from the discovery cache; an older
page is fetched again, and kept as the fallback when the source then fails. A failure with nothing stored is
reported as `SOURCE_FAILED` with its category, never as an empty list.

**Two surprises, both honest.**
- *From your sources:* a random work from the first pages of a random browsable list that is not on the
  shelf, with the source and list it came from. It looks at most six pages, first pages first.
- *From your shelf:* a random shelf work that is neither completed nor started. It costs no network request.

**Navigation.** Discover is a primary destination after Search. On a phone the bottom bar is Home, Search,
Discover, My Shelf and More; Following moves into More.

**Out of scope for now:** genres and tags (a later `genres` capability), personal recommendations, and any
scoring across sources. Recipes for each source live in the adapters repository and are reviewed there.
