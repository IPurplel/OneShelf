# WP-3 — Arabic search, before and after

Measured live 2026-09-08 against the five Arabic-serving configured
sites. **before** is the query exactly as typed, which is all the app
ever sent. **after** adds the hits recovered by the alternative
spellings, counted post-gate: what the user would actually be shown.

| variation class | query | 3asq.online | arabtoons.net | 8ghrb.com | kitaboka.com | www.noor-book.com |
|---|---|---|---|---|---|---|
| alef forms (hamza written) | `الأمير` | 8 → 8 | 0 → 0 | **12 → 16** | 0 → 0 | 6 → 6 |
| alef forms (hamza omitted) | `الامير` | 0 → 0 | 0 → 0 | 4 → 4 | 0 → 0 | 6 → 6 |
| teh marbuta | `رواية` | 7 → 7 | 6 → 6 | **1 → 13** | **12 → 20** | 0 → 0 |
| teh marbuta spelled as heh | `روايه` | **0 → 7** | **0 → 6** | **12 → 13** | **12 → 20** | 0 → 0 |
| alef maqsura | `ليلى` | **0 → 6** | **0 → 3** | **12 → 24** | **1 → 2** | 12 → 12 |
| alef maqsura spelled as yeh | `ليلي` | 6 → 6 | 3 → 3 | **12 → 24** | **1 → 2** | 12 → 12 |
| harakat present | `رِوايَة` | **0 → 7** | **0 → 6** | **0 → 13** | **12 → 20** | 0 → 0 |
| tatweel | `روايـــة` | **0 → 7** | **0 → 6** | **1 → 14** | **12 → 20** | 0 → 0 |
| arabic-indic digits | `الجزء ٢` | 1 → 1 | 0 → 0 | 12 → 12 | 2 → 2 | 9 → 9 |
| persian keheh and farsi yeh | `کتاب` | **0 → 6** | **0 → 1** | **7 → 14** | **1 → 9** | 0 → 0 |
| definite article present | `الغريب` | 10 → 10 | 1 → 1 | 12 → 12 | 2 → 2 | 12 → 12 |
| copy-paste carrying RLM | `‏الغريب‎` | 10 → 10 | 1 → 1 | 12 → 12 | 2 → 2 | 12 → 12 |
| **total** | | **42 → 75** | **11 → 33** | **97 → 171** | **57 → 99** | **69 → 69** |

Across all five sites: **276 → 447 hits**, a 62% gain.

Noor gains nothing, and that is the expected result, not a failure:
its own index already normalises, so every spelling reaches it as typed.
A site that needs no help is exactly the site the variants must not cost
anything — and they do not, because a variant is only ever sent after the
query as typed came back empty.

## The bidi mark, measured on its own

The RLM row above compares two *already cleaned* queries, so it shows only
that cleaning is harmless. What the mark actually cost had to be measured
directly, by sending the pasted string the way the old code did
(`docs/evidence/wp3/rlm-transcript.txt`):

| query | 8ghrb.com | 3asq.online |
|---|---|---|
| `‏الغريب‎` as pasted — `q.strip()` leaves both marks in | **0 hits** | **0 hits** |
| `الغريب` after `clean_query` | **12 hits** | **10 hits** |

`.strip()` does not remove them: they are not whitespace. They went into the
site's query string exactly as pasted, and matched nothing.

Inside `fold()` the same characters used to reach the `\W+` rule and become a
**space**. At the edge of a query that was harmless — the trailing `.strip()`
absorbed it — but in the middle of a word it split one token into two, and
every gate downstream then went looking for both halves separately. That case
is pinned by `test_an_invisible_mark_inside_a_word_does_not_split_it`.
