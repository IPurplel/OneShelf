# Cozy Forest — Library Decisions

Evaluated 2026-10-23 against the OneShelf frontend (React 19.3, Vite 7, TypeScript 5.9).

## Adopted

| Library | Version | Purpose | License | Bundle Impact | Decision |
|---|---|---|---|---|---|
| `tailwindcss` + `@tailwindcss/vite` | 4.x | Utility-first CSS alongside existing token system | MIT | CSS-only output, no JS runtime | Adopted |
| `lucide-react` | latest stable | Consistent icon set replacing 16 inline SVGs | ISC | Tree-shakes to ~5KB for used icons | Adopted |
| `motion` (motion.dev) | latest stable | Animations: hero crossfade, shelf hover, page transitions | MIT | ~15KB gzipped | Adopted |
| `embla-carousel-react` | latest stable | Hero carousel, optional horizontal shelf scroll | MIT | ~6KB gzipped | Adopted |
| `sonner` | latest stable | Ephemeral toast notifications (shelf actions, errors) | MIT | ~5KB gzipped | Adopted |
| `@base-ui-components/react` | latest stable | Headless accessible primitives for interactive controls | MIT | Tree-shakeable, only imported components ship | Adopted |

### Tailwind CSS 4 — Coexistence Strategy

Tailwind 4 uses CSS-first configuration via `@theme` blocks. Existing CSS custom properties from `tokens.css` are mapped into Tailwind's theme namespace. Both systems coexist:

- Existing CSS files (`tokens.css`, `base.css`, `shell.css`, `library.css`, `reader.css`) remain unchanged initially.
- New components use Tailwind utilities for layout and spacing.
- Design tokens remain the single source of truth; Tailwind references them.
- Tailwind's preflight is configured to be additive, not replace existing resets.

### Base UI — Primary Primitive Layer

Base UI provides accessible headless primitives (dialogs, popovers, tabs, toggles) styled with Tailwind utilities and the forest token palette. This replaces the need for Radix/shadcn for most interactive components.

### Motion — Reduced Motion

All Motion animations check `prefers-reduced-motion`. The shared `lib/motion.ts` module exports transition presets and the `useReducedMotion` hook.

## Deferred

| Library | Decision | Reason |
|---|---|---|
| shadcn/ui | Deferred | Depends on Radix, which overlaps with Base UI. Will add specific shadcn components only if Base UI proves insufficient for certain complex patterns. |
| TanStack Virtual | Evaluate M5 | Only needed if My Shelf shows performance issues with 1000+ items. Measure before adding. |

## Rejected

| Library | Decision | Reason |
|---|---|---|
| GSAP | Rejected | Motion handles all reference-image animation effects. Adding GSAP would create two animation engines for the same work. |
| React Three Fiber + Drei | Rejected | The existing CSS 3D shelf (`perspective`, `rotateX`, SVG grain texture) achieves the reference image's realism. R3F would add ~150KB + three.js (~150KB more), require WebGL context, and make shelf books inaccessible to screen readers without significant extra work. Mobile GPU performance would degrade. |
| TanStack Table | Rejected | No dense table views exist in the Cozy Forest design. |
| Floating UI | Rejected | Base UI includes positioning utilities. |
| Sharp | Rejected | Build-time image optimization, not a frontend runtime dependency. Can be added to the build pipeline separately if needed. |

## 3D Shelf Comparison

### CSS + Motion (Chosen)

- Uses existing `perspective(180px) rotateX(52deg)` on shelf deck.
- Layered pseudo-elements for fascia, back rail, and ambient glow.
- SVG `feTurbulence` grain texture (`shelf-grain.svg`).
- Motion adds smooth hover lifts and entrance animations.
- Total additional bundle: ~15KB (Motion only).
- Accessible: every book is a real React element with keyboard support.
- Works on all devices, no WebGL dependency.

### React Three Fiber (Rejected)

- Would require `@react-three/fiber` (~45KB) + `@react-three/drei` (~80KB) + `three` (~150KB).
- Canvas-based rendering: books become mesh objects, not DOM elements.
- Needs manual accessibility (ARIA overlays for each book).
- WebGL context can be lost; requires fallback path.
- Mobile GPU performance concerns with texture-heavy scenes.
- Verdict: visual improvement over CSS is marginal for the reference image's style; cost is disproportionate.
