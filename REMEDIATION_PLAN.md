# OneShelf — Remediation Plan

**Date:** 2026-10-24  
**Based on:** WEBSITE_AUDIT.md, BUG_REPORT.md, MISSING_FEATURES.md

---

## Priority Framework

| Priority | Definition | Target |
|---|---|---|
| P0 | App-breaking, data loss, security | Immediate |
| P1 | Visible broken UI on primary screens | Within 1 week |
| P2 | Accessibility/i18n/UX degradation | Within 2 weeks |
| P3 | Quality, polish, technical debt | Next release cycle |
| P4 | Enhancement, nice-to-have | Backlog |

---

## Phase 1: Critical Fixes (P1) — Week 1

### 1.1 Add React Error Boundary
**Effort:** Small (1-2 hours)  
**Files:** `frontend/src/app/App.tsx`, new `frontend/src/components/ErrorBoundary.tsx`  
**Risk:** None

Create an `ErrorBoundary` class component wrapping `<App>` that catches rendering errors and displays a "Something went wrong — reload the page" message with a retry button. This prevents the blank white screen crash on any uncaught render error.

### 1.2 Fix Cover Proxy 413 Retry Storm
**Effort:** Small (30 min)  
**Files:** `backend/oneshelf/api/covers.py`  
**Risk:** Low  
**Constraint:** Backend change — requires user authorization per security rules

Change the error response `Cache-Control` header from `no-store` to `private, max-age=3600` for 413 and 415 responses. This prevents the browser from retrying known-failing cover URLs on every page load. The 413 for the 3asq cover will still occur once per hour instead of 9 times per page load.

```python
def _error(status: int, code: str, message: str) -> Response:
    cache = "private, max-age=3600" if status in (413, 415) else "no-store"
    return Response(..., headers={"Cache-Control": cache})
```

### 1.3 Fix Hardcoded English aria-labels in HeroCarousel
**Effort:** Small (15 min)  
**Files:** `frontend/src/components/HeroCarousel.tsx`, `frontend/src/i18n/strings.ts`  
**Risk:** None

Add i18n keys and replace hardcoded strings:
- Add `"hero.previousSlide": "Previous slide"` / `"الشريحة السابقة"` to strings.ts
- Add `"hero.nextSlide": "Next slide"` / `"الشريحة التالية"` to strings.ts
- Replace `aria-label="Previous slide"` with `aria-label={t("hero.previousSlide")}`
- Replace `aria-label="Next slide"` with `aria-label={t("hero.nextSlide")}`

---

## Phase 2: UX & Quality (P2) — Week 2

### 2.1 Add Download Feedback in Reader
**Effort:** Small (30 min)  
**Files:** `frontend/src/features/reader/ReaderScreen.tsx`  
**Risk:** None

Wrap the "d" key download in a toast notification:
```tsx
import { toast } from "sonner";
// ...
else if (event.key === "d") {
  api.post("/api/downloads", { unit_ids: [id] })
    .then(() => toast.success(t("reader.downloadStarted")))
    .catch(() => toast.error(t("reader.downloadFailed")));
}
```
Add corresponding i18n keys.

### 2.2 Add Success/Error Toasts for Mutation Actions
**Effort:** Medium (2-3 hours)  
**Files:** `DownloadsScreen.tsx`, `FollowingScreen.tsx`, `SourcesScreen.tsx`, `ShelfScreen.tsx`  
**Risk:** Low

Replace silent `act()` wrappers with toast notifications on success and error. Sonner is already installed and `<Toaster />` is in the provider tree — components just need to call `toast()`.

### 2.3 Fix Batch TypeScript Type
**Effort:** Trivial (5 min)  
**Files:** `frontend/src/features/downloads/DownloadsScreen.tsx`  
**Risk:** None

Add `"canceled"` to the `Batch.state` union type.

### 2.4 Fix fetchPriority on WorkCard Covers
**Effort:** Small (15 min)  
**Files:** `frontend/src/components/WorkCard.tsx`  
**Risk:** None

Change `fetchPriority="high"` to `fetchPriority="auto"` on WorkCard. The hero carousel and first few visible cards can optionally pass `fetchPriority="high"` as a prop.

---

## Phase 3: Robustness (P3) — Next Release

### 3.1 JSON.parse Error Handling in API Client
**Effort:** Small (15 min)  
**Files:** `frontend/src/api/client.ts`  
**Risk:** None

Wrap `JSON.parse(text)` in try-catch, throwing an `ApiError` on parse failure.

### 3.2 AnimatePresence for Page Transitions
**Effort:** Small (30 min)  
**Files:** `frontend/src/app/App.tsx`  
**Risk:** Low — test with all routes for flicker

Wrap the `motion.div` in `<AnimatePresence mode="wait">` for proper exit animations.

### 3.3 EventSource Exponential Backoff
**Effort:** Small (30 min)  
**Files:** `frontend/src/app/live.tsx`  
**Risk:** None

Replace fixed 2-second reconnect with exponential backoff:
```typescript
const backoff = Math.min(RECONNECT_MS * Math.pow(2, attempts), 60000);
```
Reset `attempts` on successful connection.

### 3.4 Make Notification Items Clickable
**Effort:** Medium (2-3 hours)  
**Files:** `frontend/src/features/notifications/NotificationsDrawer.tsx`  
**Risk:** Low — needs work_id / source_id from notification payload

Render notification items as `<Link>` when their payload contains a navigable target (work_id → `/works/:id`, source_id → `/sources`).

---

## Phase 4: Enhancements (P4) — Backlog

### 4.1 Cover Proxy Image Resizing
**Effort:** Large (1-2 days)  
**Files:** `backend/oneshelf/api/covers.py`  
**Risk:** Medium — adds Pillow dependency, CPU cost  
**Constraint:** Backend change

Add server-side image resizing to cap cover dimensions at 600px width and convert to WebP where the client supports it. This eliminates 413 errors entirely and reduces bandwidth.

### 4.2 PWA Support
**Effort:** Large (1-2 days)  
**Files:** `frontend/public/manifest.json` (new), `frontend/public/sw.js` (new), `frontend/index.html`  
**Risk:** Medium

Add a web app manifest and a service worker for:
- Static asset caching (CSS, JS, fonts)
- Offline fallback page
- "Add to Home Screen" on mobile

### 4.3 Keyboard Shortcut Help in Reader
**Effort:** Small (1-2 hours)  
**Files:** `frontend/src/features/reader/ReaderScreen.tsx`  
**Risk:** None

Add a "Keyboard shortcuts" panel accessible from the reader's More menu, listing all available shortcuts.

### 4.4 Shelf Batch Operations
**Effort:** Medium (3-4 hours)  
**Files:** `frontend/src/features/shelf/ShelfScreen.tsx`  
**Risk:** Low

Add multi-select mode with checkboxes and batch actions (remove, favorite, download all).

### 4.5 Expand Shelf "Manage" Dialog
**Effort:** Small (1 hour)  
**Files:** `frontend/src/features/shelf/ShelfScreen.tsx`  
**Risk:** None

Add Favorite, Pin, Download, and View Details actions to the manage dialog.

---

## Implementation Order Summary

```
Week 1 (P1):
  1.1  Error Boundary               [frontend]  ~1h
  1.2  Cache 413 error responses     [backend]   ~30m  ⚠ needs user auth
  1.3  HeroCarousel aria-labels i18n [frontend]  ~15m

Week 2 (P2):
  2.1  Reader download feedback      [frontend]  ~30m
  2.2  Toast notifications for all   [frontend]  ~2h
  2.3  Fix Batch TS type             [frontend]  ~5m
  2.4  Fix fetchPriority             [frontend]  ~15m

Next release (P3):
  3.1  API client JSON.parse         [frontend]  ~15m
  3.2  AnimatePresence               [frontend]  ~30m
  3.3  SSE exponential backoff       [frontend]  ~30m
  3.4  Clickable notifications       [frontend]  ~2h

Backlog (P4):
  4.1  Cover image resizing          [backend]   ~1-2d  ⚠ needs user auth
  4.2  PWA support                   [frontend]  ~1-2d
  4.3  Keyboard shortcut help        [frontend]  ~1h
  4.4  Shelf batch operations        [frontend]  ~3h
  4.5  Expand manage dialog          [frontend]  ~1h
```

---

## Constraints & Notes

1. **Backend changes** (1.2, 4.1) require explicit user authorization per the project security rules. These should not be implemented without approval.
2. **No deployment** — all changes should be committed to the branch and pushed. The user manages their own production deployment.
3. **PRs #6 and #10** both modify `library.css`, `strings.ts`, and 5 feature screen files. Coordinate changes to avoid merge conflicts.
4. **No profile/avatar** — the existing test (`shell.test.tsx:33`) enforces no avatar icon. Do not add one.
5. **All 478 tests must continue to pass** after each change.
