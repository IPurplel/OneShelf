# OneShelf — Test Matrix

**Date:** 2026-10-24  
**Purpose:** Regression testing checklist for each remediation item and ongoing QA

---

## Notation

- **[A]** = Automated test exists
- **[M]** = Manual verification required
- **[P]** = Partial automation (some aspects covered)

---

## 1. Per-Route Smoke Tests

| Route | Load | Console Errors | Network OK | Theme Toggle | RTL Toggle |
|---|---|---|---|---|---|
| `/` (Home) | [A] | [M] 413 cover known | [P] | [M] | [M] |
| `/search` | [A] | [M] | [M] | [M] | [M] |
| `/shelf` | [A] | [M] | [M] | [M] | [M] |
| `/following` | [A] | [M] | [M] | [M] | [M] |
| `/downloads` | [A] | [M] | [M] | [M] | [M] |
| `/sources` | [A] | [M] | [M] | [M] | [M] |
| `/settings` | [A] | [M] | [M] | [M] | [M] |
| `/settings/:section` | [A] | [M] | [M] | [M] | [M] |
| `/first-run` | [A] | [M] | [M] | [M] | [M] |
| `/works/:id` | [A] | [M] | [M] | [M] | [M] |
| `/read/:unitId` | [A] | [M] | [M] | [M] | [M] |

---

## 2. Responsive Breakpoint Matrix

| Screen | 320px | 390px | 768px | 1024px | 1440px | 1920px |
|---|---|---|---|---|---|---|
| Home | [M] | [M] | [M] | [M] | [M] | [M] |
| Search | [M] | [M] | [M] | [M] | [M] | [M] |
| Shelf | [M] | [M] | [M] | [M] | [M] | [M] |
| Work Details | [M] | [M] | [M] | [M] | [M] | [M] |
| Reader | [M] | [M] | [M] | [M] | [M] | [M] |
| Settings | [M] | [M] | [M] | [M] | [M] | [M] |

**Check at each breakpoint:**
- [ ] No horizontal overflow / scroll
- [ ] Navigation mode correct (sidebar vs bottom nav at 900px)
- [ ] Touch targets ≥ 44px
- [ ] Text readable without zoom
- [ ] Hero carousel properly sized
- [ ] Shelf cards don't overflow

---

## 3. Feature Test Cases

### 3.1 Home Screen
| Test Case | Type | Status |
|---|---|---|
| Hero carousel renders with slides | [A] | Pass |
| Hero carousel prev/next navigation | [A] | Pass |
| Hero carousel auto-play (6s interval) | [A] | Pass |
| Hero carousel pauses on hover | [A] | Pass |
| Hero carousel RTL direction reverses | [A] | Pass |
| Continue Reading shelf shows items | [A] | Pass |
| Trending shelf from search results | [A] | Pass |
| Latest / Recently Added two-column | [A] | Pass |
| Empty library state | [A] | Pass |
| Cover fallback to CoverPlaceholder | [A] | Pass |
| 413 cover shows placeholder (not blank) | [M] | Pass |

### 3.2 Search
| Test Case | Type | Status |
|---|---|---|
| Submit search query | [A] | Pass |
| Progressive results via SSE | [A] | Pass |
| Failed source shows retry button | [A] | Pass |
| Retry single source | [A] | Pass |
| Category scope filter | [A] | Pass |
| Language scope filter | [A] | Pass |
| Grid/List layout toggle | [A] | Pass |
| Empty results state | [A] | Pass |
| Offline error state | [A] | Pass |
| Stream error recovery | [A] | Pass |

### 3.3 My Shelf
| Test Case | Type | Status |
|---|---|---|
| View tabs (All, Saved, Reading, etc.) | [A] | Pass |
| Tab keyboard navigation | [A] | Pass |
| Local search filter | [A] | Pass |
| Sort by added / title | [A] | Pass |
| Grid/List layout toggle | [A] | Pass |
| Remove work (with files dialog) | [A] | Pass |
| Empty state per view | [A] | Pass |
| Shelf case grid rendering | [A] | Pass |

### 3.4 Work Details
| Test Case | Type | Status |
|---|---|---|
| Cover image with fallback | [A] | Pass |
| Metadata display (creator, type, aliases) | [A] | Pass |
| Track tabs (Read, Details, Sources) | [A] | Pass |
| Unit list rendering | [A] | Pass |
| Download actions (single, all, track) | [A] | Pass |
| Shelf actions (add, favorite, pin) | [A] | Pass |
| Follow/Unfollow | [A] | Pass |
| Continue reading button | [A] | Pass |
| Export menu | [A] | Pass |

### 3.5 Reader
| Test Case | Type | Status |
|---|---|---|
| Pages load from API | [A] | Pass |
| Single page mode | [A] | Pass |
| Double page mode | [A] | Pass |
| Long strip mode | [A] | Pass |
| Keyboard navigation (arrows, space) | [A] | Pass |
| Touch swipe navigation | [A] | Pass |
| Zoom (pinch, ctrl+wheel, +/-) | [A] | Pass |
| Pan while zoomed | [A] | Pass |
| Fullscreen toggle | [A] | Pass |
| Progress scrubber | [A] | Pass |
| Resume position from library | [A] | Pass |
| Auto-hide controls (smart mode) | [A] | Pass |
| Minimal controls mode | [A] | Pass |
| End of unit → next unit link | [A] | Pass |
| Contents drawer | [A] | Pass |
| Settings panel | [A] | Pass |
| Source switch | [A] | Pass |
| Failed page → retry/repair/skip | [A] | Pass |
| Mark read/unread | [A] | Pass |
| RTL reading direction | [A] | Pass |
| "d" key silent download | [M] | **Bug (BUG-003)** |

### 3.6 Following
| Test Case | Type | Status |
|---|---|---|
| Sections: New / Attention / Current | [A] | Pass |
| Check single follow | [A] | Pass |
| Check all follows | [A] | Pass |
| Empty state | [A] | Pass |
| Live event refresh | [A] | Pass |
| Degraded/reconnect states | [A] | Pass |

### 3.7 Downloads
| Test Case | Type | Status |
|---|---|---|
| Batch list rendering | [A] | Pass |
| Batch state badges | [A] | Pass |
| Progress bars | [A] | Pass |
| Pause/Resume batch | [A] | Pass |
| Cancel batch | [A] | Pass |
| Retry failed jobs | [A] | Pass |
| Batch details expansion | [A] | Pass |
| Job-level status display | [A] | Pass |
| Clear history (confirm dialog) | [A] | Pass |
| Open completed unit | [A] | Pass |
| Pagination in batch details | [A] | Pass |
| Live event refresh | [A] | Pass |
| "canceled" batch state display | [M] | **Fixed (bf97c90)** |

### 3.8 Sources
| Test Case | Type | Status |
|---|---|---|
| Source list rendering | [A] | Pass |
| Category filter chips | [A] | Pass |
| Language filter chips | [A] | Pass |
| More drawer (details) | [A] | Pass |
| Enable/Disable source | [A] | Pass |
| Remove source (confirm dialog) | [A] | Pass |
| Login session management | [A] | Pass |
| Registry panel | [A] | Pass |
| Install from file | [A] | Pass |
| Live event refresh | [A] | Pass |

### 3.9 Settings
| Test Case | Type | Status |
|---|---|---|
| Tab navigation (10 categories) | [A] | Pass |
| Language switch (en ↔ ar) | [A] | Pass |
| Theme switch (light/dark/system) | [A] | Pass |
| URL-driven tab selection | [A] | Pass |
| Overflow scroll on narrow viewport | [A] | Pass |
| All sub-panels render | [P] | Pass |

### 3.10 Notifications
| Test Case | Type | Status |
|---|---|---|
| Notification list rendering | [A] | Pass |
| Mark all seen | [A] | Pass |
| Clear seen | [A] | Pass |
| Needs Attention filter | [A] | Pass |
| Empty state | [A] | Pass |
| Live event refresh | [A] | Pass |
| Badge count in header | [A] | Pass |

---

## 4. Remediation Verification Tests

### Phase 1 Fixes

| Fix | Test to Run | Expected Result |
|---|---|---|
| 1.1 Error Boundary | Inject render error in a component | App shows fallback UI, not white screen |
| 1.2 Cache 413 responses | Load Home, check Network tab | 413 request sent once, cached on reload |
| 1.3 HeroCarousel aria i18n | Switch to Arabic, inspect carousel buttons | `aria-label` in Arabic |

### Phase 2 Fixes

| Fix | Test to Run | Expected Result |
|---|---|---|
| 2.1 Download feedback | Press "d" in reader | Toast shows "Download started" |
| 2.2 Toast notifications | Pause/resume a batch | Toast confirms action |
| 2.3 Batch TS type | `tsc --noEmit` | No type errors |
| 2.4 fetchPriority | Load shelf with 20+ items, check Network | Only first few images are high priority |

### Phase 3 Fixes

| Fix | Test to Run | Expected Result |
|---|---|---|
| 3.1 JSON.parse handling | Proxy returns HTML 200 | User-friendly error, not SyntaxError |
| 3.2 AnimatePresence | Navigate between routes | Smooth crossfade transition |
| 3.3 SSE backoff | Stop backend, watch reconnects | Backoff from 2s to 60s max |
| 3.4 Clickable notifications | Click a notification with work_id | Navigates to work details |

---

## 5. Adapter Integration Tests

| Adapter | Search | Work Details | Reader | Download |
|---|---|---|---|---|
| 3asq | [M] Search Arabic manga | [M] Open work | [M] Read pages | [M] Download unit |
| Arabic Collections (NYU) | [M] Search books | [M] Open work | [M] Read pages | [M] Download |
| MangaDex | [M] Search multi-lang | [M] Open work | [M] Read pages | [M] Download |
| Pepper&Carrot | [M] Search comics | [M] Open work | [M] Read pages | [M] Download |
| Project Gutenberg | [M] Search books | [M] Open work | [M] Read pages | [M] Download |
| Safahat (Hindawi) | [M] Search Arabic | [M] Open work | [M] Read pages | [M] Download |
| Standard Ebooks | [M] Search ebooks | [M] Open work | [M] Read pages | [M] Download |
| Tapas | [M] Search webtoons | [M] Open work | [M] Read pages | [M] Download |
| WEBTOON | [M] Search webtoons | [M] Open work | [M] Read pages | [M] Download |
| arXiv | [M] Search papers | [M] Open work | [M] Read pages | [M] Download |

**Last verified:** 2026-10-23 (all 10 adapters confirmed Active on production)

---

## 6. Theme & i18n Matrix

| Check | Light EN | Dark EN | Light AR | Dark AR |
|---|---|---|---|---|
| Sidebar colors | [M] | [M] | [M] | [M] |
| Hero gradient | [M] | [M] | [M] | [M] |
| Card shadows | [M] | [M] | [M] | [M] |
| Text contrast | [M] | [M] | [M] | [M] |
| Input fields | [M] | [M] | [M] | [M] |
| Buttons | [M] | [M] | [M] | [M] |
| Progress bars | [M] | [M] | [M] | [M] |
| Bottom nav (mobile) | [M] | [M] | [M] | [M] |
| RTL layout | N/A | N/A | [M] | [M] |
| Direction-aware icons | N/A | N/A | [M] | [M] |

---

## 7. Build Verification

| Check | Command | Expected |
|---|---|---|
| Unit tests | `npm test` | 478 pass, 0 fail |
| Type check | `npx tsc --noEmit` | 0 errors |
| Production build | `npm run build` | Success, no warnings |
| Bundle size | Check `dist/` output | CSS ≤ 70KB, JS ≤ 235KB (gzipped) |
| Dead CSS | Audit `library.css`, `shell.css` | 0 unused rules |
