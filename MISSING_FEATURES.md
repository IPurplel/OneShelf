# OneShelf — Missing Features & Incomplete Implementations

**Date:** 2026-10-23

---

## Category: Critical Missing

### MF-001: No Error Boundary

**Severity:** High  
**Location:** `frontend/src/app/App.tsx`

The app has no React Error Boundary. An uncaught rendering error in any component will crash the entire application, showing a blank white screen with no recovery path.

**Impact:** A single malformed API response, a corrupted cover image, or an unexpected null reference can make the entire app unusable until the user manually refreshes.

**Recommended:** Add an `ErrorBoundary` component at the `<App>` level that catches rendering errors and shows a "Something went wrong — reload" message.

---

### MF-002: No PWA / Offline Support

**Severity:** Medium  
**Location:** `frontend/public/` (missing manifest.json, service worker)

There is no `manifest.json`, no service worker, and no offline caching strategy. The app requires a live connection to the backend at all times.

**Impact:** 
- Cannot install as a PWA on mobile devices
- No offline access to already-downloaded works
- No caching of static assets beyond browser defaults
- Poor mobile experience (no "Add to Home Screen" prompt)

**Recommended:** Add a service worker with at minimum static asset caching (CSS, JS, fonts) and a manifest.json for installability.

---

## Category: UI/UX Gaps

### MF-003: Notification Items Not Actionable

**Severity:** Medium  
**Location:** `frontend/src/features/notifications/NotificationsDrawer.tsx:60-68`

Notification items display title and summary as plain text. They do not link to the related work, source, or relevant screen. Users cannot click a notification to navigate to the relevant context.

**Impact:** Users must manually navigate to find what a notification is about.

**Recommended:** Add navigation links to notifications based on their `payload` data (work_id → work details, source_id → sources).

---

### MF-004: No Batch Operations on My Shelf

**Severity:** Low  
**Location:** `frontend/src/features/shelf/ShelfScreen.tsx`

The shelf supports only single-item management (via "Manage" button → Remove). There is no multi-select for batch operations like:
- Remove multiple works at once
- Mark multiple as favorite/completed
- Download all units for multiple works
- Export a selection

**Impact:** Managing a large library requires repetitive one-by-one actions.

---

### MF-005: No Keyboard Shortcut Help / Discovery

**Severity:** Medium  
**Location:** `frontend/src/features/reader/ReaderScreen.tsx:286-304`

The reader has 12 keyboard shortcuts (arrows, space, t, s, f, d, +/-, 0) but no discoverable help UI. Users must discover these by trial and error.

**Impact:** Power users don't know about useful shortcuts; casual users may accidentally trigger actions (especially "d" for download).

**Recommended:** Add a "Keyboard shortcuts" section in the reader's More menu or Settings panel, or show a tooltip overlay on first use.

---

### MF-006: No Reading Statistics or History

**Severity:** Low  
**Location:** N/A (not implemented)

There is no way to view:
- Total pages/chapters read
- Reading time estimates
- Completion history timeline
- Activity heatmap or streak tracker

**Impact:** Users cannot track their reading habits or progress over time.

---

### MF-007: No Search Within Work / Unit Content

**Severity:** Low  
**Location:** N/A (not implemented)

The reader has no text search functionality. For text-based content (books, articles), users cannot search within the current work.

**Impact:** Reduces usability for research and reference material (especially arXiv papers and Gutenberg books).

---

## Category: Technical Debt

### MF-008: Cover Proxy Has No Image Resizing

**Severity:** Medium  
**Location:** `backend/oneshelf/api/covers.py`

The cover proxy serves images at their original size with no resizing, compression, or format conversion. A 5000x7000 JPEG is served as-is, even though it's displayed at 120px wide on a work card.

**Impact:**
- Wasted bandwidth (especially on mobile)
- Slow cover loading for large originals
- 413 errors for images > 4MB (BUG-001)

**Recommended:** Add server-side image resizing (e.g., max 600px width for covers, WebP conversion where supported).

---

### MF-009: No Loading Skeleton for Cover Images

**Severity:** Low  
**Location:** `frontend/src/components/WorkCard.tsx`

While `CoverPlaceholder` is shown as a fallback for missing/failed covers, there is no skeleton loading state while covers are in flight. The placeholder appears instantly, then "pops" to the actual cover when it loads.

**Impact:** Visual jank during initial page load, especially on slow connections.

**Recommended:** Use a shimmer/skeleton animation over the placeholder area while the image loads.

---

### MF-010: EventSource Reconnect Strategy Could Cause Storms

**Severity:** Low  
**Location:** `frontend/src/app/live.tsx:74, 79`

The SSE reconnect uses a fixed 2-second interval:
```typescript
retry = setTimeout(open, RECONNECT_MS);
```

If the server is down, this creates a reconnect every 2 seconds indefinitely, with no exponential backoff.

**Impact:** Under server downtime, the client generates a connection attempt every 2 seconds. With multiple browser tabs open, this multiplies.

**Recommended:** Implement exponential backoff (e.g., 2s, 4s, 8s, 16s, max 60s) for reconnection attempts.

---

### MF-011: No Confirmation Toast for Successful Actions

**Severity:** Medium  
**Location:** Multiple screens (Downloads, Following, Sources, Shelf)

Actions like "Pause batch", "Resume batch", "Retry failed", "Check all follows", "Disable source" succeed or fail silently — the only feedback is the data refreshing. There is no toast or success message.

Sonner is installed but only used as `<Toaster />` in the provider tree — no components actually call `toast()`.

**Impact:** Users are unsure whether their action was registered, especially for network-dependent operations.

**Recommended:** Use Sonner `toast.success()` / `toast.error()` for all mutation actions.

---

### MF-012: Shelf "Manage" Dialog Offers Only Remove

**Severity:** Low  
**Location:** `frontend/src/features/shelf/ShelfScreen.tsx:156-167`

The "Manage" modal for a shelf item only offers "Cancel" and "Remove". Other useful actions are missing:
- Toggle Favorite
- Toggle Pin
- Download all units
- View work details
- Unfollow

These actions are available on the Work Details page but not from the shelf list view.

**Recommended:** Expand the manage dialog to include quick-actions, or replace with a context menu.
