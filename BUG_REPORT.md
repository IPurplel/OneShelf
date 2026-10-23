# OneShelf — Bug Report

**Date:** 2026-10-23  
**Environment:** Production at http://192.168.8.32:8420

---

## BUG-001: Cover Proxy Returns 413 for Large Cover Images (P1)

**Location:** Backend `oneshelf/api/covers.py:27`, `covers.py:57-58`  
**Affected:** Home hero carousel, Continue Reading shelf, any work using oversized cover art  
**Severity:** P1 — visible broken UI on the landing page

**Description:** The cover proxy enforces a `MAX_COVER_BYTES = 4 * 1024 * 1024` (4MB) limit. One specific 3asq cover (`1000132867.jpg`) exceeds this limit, causing a 413 response. The frontend falls back to `CoverPlaceholder` gracefully, but:
1. The hero carousel shows a text placeholder instead of the cover art for that work
2. The 413 response uses `Cache-Control: no-store`, meaning every page load retries the failing request
3. Console fills with error messages (9 per Home page load)
4. Multiple works may reference the same oversized cover, multiplying the errors

**Expected:** Cover images should be resized/compressed by the proxy, or the error should be cached to avoid repeated failures.

**Reproduction:**
1. Navigate to http://192.168.8.32:8420/
2. Open browser DevTools → Console
3. Observe "413 Content Too Large" errors for `/api/covers?source=oneshelf.3asq&url=...1000132867.jpg`

**Recommended Fix:**
- Option A: Add image resizing in the cover proxy (e.g., Pillow/sharp to resize images > 4MB before serving)
- Option B: Cache 413 responses with a short `max-age` (e.g., 1 hour) to prevent retry storms
- Option C: Increase `MAX_COVER_BYTES` (least recommended — 4MB is already generous)

---

## BUG-002: Hardcoded English aria-labels in Hero Carousel (P2)

**Location:** `frontend/src/components/HeroCarousel.tsx:86, 89`  
**Affected:** Screen reader users in Arabic mode  
**Severity:** P2 — accessibility/i18n bug

**Description:** The hero carousel's previous/next buttons have hardcoded English `aria-label` attributes:
```tsx
<button ... aria-label="Previous slide">
<button ... aria-label="Next slide">
```

These should use the `t()` function for internationalization.

**Expected:** `aria-label={t("hero.previousSlide")}` and `aria-label={t("hero.nextSlide")}`

**Recommended Fix:** Add i18n keys `hero.previousSlide` and `hero.nextSlide` to `strings.ts` in both English and Arabic sections, and update the JSX.

---

## BUG-003: Silent Download on "d" Keypress in Reader (P2)

**Location:** `frontend/src/features/reader/ReaderScreen.tsx:298`  
**Affected:** Reader keyboard users  
**Severity:** P2 — unexpected side effect without feedback

**Description:** Pressing "d" in the reader triggers a download API call with no confirmation dialog, no loading indicator, and no success/error feedback:
```tsx
else if (event.key === "d") void api.post("/api/downloads", { unit_ids: [id] });
```

A user could accidentally trigger downloads by pressing "d" while typing or navigating. There is no visual indication that a download was initiated.

**Expected:** Either a confirmation prompt, a toast notification on success/failure, or at minimum a visual indicator.

**Recommended Fix:** Use Sonner toast to show "Download started" on success or "Download failed" on error.

---

## BUG-004: Missing "canceled" in Batch TypeScript Type (P3)

**Location:** `frontend/src/features/downloads/DownloadsScreen.tsx:16`  
**Affected:** Type safety for download batch states  
**Severity:** P3 — type inconsistency (i18n key already fixed)

**Description:** The `Batch` type defines states as:
```typescript
state: "active" | "paused" | "completed" | "completed_with_issues" | "failed";
```
But the backend also returns `"canceled"` as a valid batch state. The i18n key `downloads.state.canceled` was added in commit `bf97c90`, but the TypeScript type was not updated.

**Expected:** Type should include `"canceled"`:
```typescript
state: "active" | "paused" | "completed" | "completed_with_issues" | "failed" | "canceled";
```

---

## BUG-005: fetchPriority="high" on All Cover Images (P3)

**Location:** `frontend/src/components/WorkCard.tsx:67`  
**Affected:** Performance — browser image prioritization  
**Severity:** P3 — performance degradation

**Description:** Every `WorkCard` cover image has `fetchPriority="high"`:
```tsx
<img src={work.cover_url!} alt="" loading="lazy" decoding="async" fetchPriority="high" ...>
```

When many cards are visible (e.g., a search with 20+ results), all images compete for high priority, defeating the purpose of `fetchPriority`. The `loading="lazy"` partially mitigates this, but images within the `IntersectionObserver`'s 240px rootMargin all become high-priority simultaneously.

**Expected:** Only above-the-fold or hero images should be high priority. Below-fold images should use `fetchPriority="auto"` or `"low"`.

**Recommended Fix:** Pass `fetchPriority` as a prop, defaulting to `"auto"`. Set `"high"` only for the first few visible cards.

---

## BUG-006: JSON.parse Without Try-Catch in API Client (P3)

**Location:** `frontend/src/api/client.ts:29`  
**Affected:** Error handling when backend returns malformed responses  
**Severity:** P3 — poor error message on edge case

**Description:** The API client parses response bodies with:
```typescript
const payload = text ? JSON.parse(text) : null;
```

If the server returns a 200 with malformed JSON (e.g., an nginx error page, a proxy timeout HTML response), this throws an uncaught `SyntaxError` with an unhelpful message like "Unexpected token < in JSON at position 0" instead of a user-friendly error.

**Expected:** Catch `SyntaxError` and throw an `ApiError` with a clear message.

**Recommended Fix:**
```typescript
let payload;
try {
  payload = text ? JSON.parse(text) : null;
} catch {
  throw new ApiError(response.status, "PARSE_FAILED", "The server returned an unexpected response.");
}
```

---

## BUG-007: No AnimatePresence for Page Transition Exit Animations (P3)

**Location:** `frontend/src/app/App.tsx:37-43`  
**Affected:** Page transition visual quality  
**Severity:** P3 — cosmetic

**Description:** The `motion.div` wrapping `<Outlet>` uses `key={location.pathname}` for entry animations, but there is no `AnimatePresence` wrapper:
```tsx
<motion.div
  key={location.pathname}
  initial={{ opacity: 0 }}
  animate={{ opacity: 1 }}
  transition={TRANSITION_EASE}
>
  <Outlet />
</motion.div>
```

Without `AnimatePresence`, when the route changes, the old page is instantly removed from the DOM (no exit animation), and only the new page fades in. This creates an asymmetric transition.

**Expected:** Wrap in `AnimatePresence` with `mode="wait"` or `mode="popLayout"` for smooth crossfade.

---

## BUG-008: 413 Error Response Not Cached (P2)

**Location:** Backend `oneshelf/api/covers.py:40`  
**Affected:** Performance on pages with oversized covers  
**Severity:** P2 — repeated failing requests on every page load

**Description:** Error responses from the cover proxy use `Cache-Control: no-store`:
```python
return Response(..., headers={"Cache-Control": "no-store"})
```

This means every time the Home page loads, the browser re-requests the known-failing cover URL, generating console errors and wasted network requests. A single page load can trigger 3-9 requests for the same failing URL.

**Expected:** Cache error responses for a reasonable duration (e.g., `max-age=3600`) to prevent retry storms.
