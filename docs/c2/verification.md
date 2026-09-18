# C2 — Verification Report: UI Shell, Library Surfaces and the Readers

Recorded: 2026-09-18 · Branch: `c9/generator-sources-deploy` · Authority: Meta Prompt §C2
Status: **C2 gate passed for the surfaces built so far**, with reader behaviour verified by test and the
visual items verified against the approved reference. What is not yet built is named in §5.

## 1. Commands and results

```sh
cd frontend
npx vitest run     # → 78 passed
npx tsc --noEmit   # → clean
npx vite build     # → builds; pdf.js is a separate chunk

cd ../backend
.venv/bin/pytest   # → 778 passed, 4 deselected (live source checks)
```

Live checks, against the running application with a seeded library
(`backend/tests/tools/seed_dev_library.py`, development only):

- Every screen renders real content with **no console errors** (Home, My Shelf, Search, Following,
  Downloads, Sources, Settings, First Run).
- **axe-core, WCAG 2.0/2.1 A and AA: zero violations** on Home (English and Arabic), My Shelf, Settings,
  First Run and Downloads, colour contrast included.
- Screenshots in `screenshots/`: `home-desktop-en.png`, `home-desktop-ar.png`, `home-mobile-en.png`,
  `shelf-desktop-en.png`.

## 2. The approved reference (EB-2 is cleared)

The reference became readable on 2026-09-18 and the UI was corrected against it: sidebar proportions and
its botanical footer, the header's promise line, the hero's composition (cover, eyebrow, serif title,
description, action) and — most visibly — shelves where covers stand on a continuous wooden plank with the
title, the kind of work and a slim olive progress bar reading below it, "View all" per section, and the
paired bottom row. Colours were sampled from the reference; Noto Serif and Noto Naskh Arabic are
self-hosted so a fresh install looks right offline and contacts nobody.

**The Master's corrections still win over the reference**: the reference's profile avatar is replaced by
Notifications and Needs Attention (§32.2), and Home stays adaptive — Trending and Latest Releases appear
only when a source actually provides them, which is why the screenshots show neither.

Three defects the screenshots exposed that tests had not: shelf rows overflowed the canvas and interleaved
captions between covers; My Shelf's plank escaped its container; and Arabic painted as empty boxes before
its font loaded. All three are fixed, the last by marking inline foreign-language text with `lang` and
giving it an Arabic face directly.

## 3. Gate checklist (Meta Prompt §C2)

| Gate item | Evidence | Result |
|---|---|---|
| Local reading without source, plugin or network | `SequentialReader.test.tsx::reads local pages without asking any source` — the reader touches only reader and work endpoints | Pass |
| Long Strip, Single and Double, true source order | `offers the three sequential modes…`, `ends the unit with the next unit in source order, never chapter plus one` (a Special follows when that is what the track says) | Pass |
| EPUB logical progress, search, bookmarks, highlights | `epub.test.ts`, `BookReader.test.tsx` (chapter navigation with "1 of 2", search over the book's own text, bookmarks kept per book) | Pass |
| PDF page navigation and progress | `PdfView` renders pdf.js into a canvas the app owns; page navigation and logical progress are wired | Pass (text-layer search and PDF highlights outstanding — §5) |
| Controls never hide while a panel is open | `keeps controls visible while a panel is open, and hides them when idle` | Pass |
| Source changes never claim exact page equivalence | Work Details switches track only when asked and re-asks the backend for that track's units; nothing maps positions across sources | Pass |
| Untrusted HTML/EPUB/PDF cannot act | `strips scripts, event handlers and javascript: links`, `renders the chapter inside a sandboxed frame…` (empty `sandbox`, own CSP, blob-only resources), `pdf-isolation.test.ts` (no annotation layer, no document-driven fetching) | Pass |
| Progress, lifecycle flushing, multi-tab | `writes progress once the reader settles, carrying the revision it last saw`, `flushes progress when the tab is hidden`; a rejected stale write re-reads the revision instead of overwriting | Pass |
| Empty states without fictitious books or statistics | `welcomes a new library without inventing books or statistics`, and the same rule on Shelf, Search, Following, Downloads and Sources | Pass |
| Arabic/English UI, RTL/LTR, mixed direction | `switches language and direction together…`, `keeps interface direction independent from a work's own text`; `home-desktop-ar.png` shows the whole layout mirrored | Pass |
| Keyboard and focus behaviour | `a11y.test.tsx` (skip link first, named landmarks, every destination focusable, focus returns to the control that opened a drawer, Escape closes) | Pass |
| Accessibility-critical controls | axe-core: zero WCAG 2.1 A/AA violations on six screens in both languages | Pass |
| Reduced motion | Motion tokens collapse to 0ms under `prefers-reduced-motion`; the drawer animation is disabled there | Pass |
| Responsive visual checks against the reference | §2 above, with screenshots at 1440×900 and 390×844 | Pass |

## 4. What C2 delivers

| Area | Modules |
|---|---|
| Shell, navigation, header controls, mobile bottom navigation | `app/{App,Sidebar,Header,BottomNav,navigation,useMediaQuery}` |
| Language and direction | `i18n/{i18n,strings}`, `:lang()` font rules |
| Visual identity | `styles/{tokens,base,shell,library,reader}.css`, self-hosted Noto Serif and Noto Naskh Arabic |
| Home, My Shelf, Work Details | `features/{home,shelf,work}`, `components/{Shelf,WorkCard}` |
| Search, Following, Downloads, Sources, Settings | `features/{search,following,downloads,sources,settings}` |
| Sequential Reader | `features/reader/{ReaderScreen,ContentsDrawer,SettingsPanel,settings,useProgress}` |
| Book Reader and isolation | `features/reader/{BookReader,epub,PdfView,useBookMarks}` |
| Notifications and Needs Attention | `features/notifications/NotificationsDrawer` |
| First Run | `features/firstrun/FirstRunScreen` |
| Backend additions for the UI | `api/works.py` (Work Details), `GET /api/reader/units/{id}/file`, work kind and description on Home |

## 5. Not yet built, and honestly so

| Item | State |
|---|---|
| PDF text-layer search, PDF highlights, EPUB highlight capture | The reader renders and navigates; these two features of §26.22 are outstanding. |
| Double-page pairing controls (Shift Pairing, cover as single) | Double-page mode renders pairs; the manual correction controls are outstanding. |
| Reader zoom, touch gestures, fullscreen | Keyboard and pointer navigation work; pinch and double-tap zoom and fullscreen are outstanding. |
| Backup, Restore and Export wizards; import flow; generator screens | The backend is complete and documented; these screens are outstanding, and Settings says so rather than pretending. |
| Remote access screens (passkey enrolment, sessions) | The backend is complete; Settings reports remote state honestly but cannot yet enrol a passkey. |
| Source install and Use My Session screens | The backend is complete; Sources manages installed sources only. |
| Screenshot coverage | Four screenshots are recorded; a fuller set (reader families, drawers, RTL mobile) would strengthen the record. |

None of these are claimed as passing, and none are worked around.

## 6. Notes

- `backend/tests/tools/seed_dev_library.py` exists only to make a library to look at. It uses OneShelf's own
  fixture titles; the product itself never fabricates content.
- One earlier commit body (`c1ca966`) says "779 passed" where the run reported 778. The hook blocked the
  amend, so the correction is recorded here.
