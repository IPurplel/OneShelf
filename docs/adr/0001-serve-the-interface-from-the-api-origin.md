# ADR 0001 — The interface is served from the API's own origin

**Date:** 2026-09-21 · **Status:** Accepted · **Context:** the release requirement that a clone plus
`./install.sh` gives a working OneShelf

## The situation

The container image built an API and no interface. `vite.config.ts` had always said "the SPA is served
from the same origin as the API in production", and in development Vite proxies `/api` to the backend
so that cookies, the Origin check and the Host allowlist behave as they will in production. But
nothing implemented the production half: the Dockerfile copied `backend/` only, so anyone who
installed OneShelf got an API with no way to use it.

## The decision

The frontend is built in a first stage of the image and served by the ASGI app itself, from the same
origin, mounted **after** the API routers.

## Why not the alternatives

*A second container running nginx* would mean two processes, two images and a reverse proxy to
configure, for a single-user application that the Master describes as one container with explicit
mounts (§2.1). It would also put the interface outside the access classifier unless that were
duplicated there — which is exactly the kind of boundary duplication that goes wrong quietly.

*A separate origin* would turn every API call into a cross-origin request, which would mean CORS,
`SameSite=None` cookies, and a weaker CSRF story than the Origin check the app already relies on
(§28). Same-origin keeps all of that as it is.

## What it commits us to

* Static serving sits **inside** the access boundary: a remote client is refused before it reaches
  `index.html`, the same as for any API route. A test holds this.
* `/api/...` is always the API's. A route that does not exist returns a JSON 404, never the interface
  loading as though nothing were wrong — otherwise a broken client call would look like a working page.
* Client-side routes fall back to `index.html`, because the SPA owns its own routing.
* Nothing outside the web root can be reached through it.
* A source checkout with no build still runs: the API serves itself and nothing else.

Untrusted document rendering is unaffected — EPUB still renders in a sandboxed iframe with its own CSP
and pdf.js still runs without scripting (§27). Serving our own built assets from our own origin does
not touch that isolation.
