import { vi } from "vitest";

type Route = { match: (url: string, init?: RequestInit) => boolean; payload: unknown; status?: number };

/** Requests carry JSON, a file, or nothing; a test should be able to see all three. */
function parseBody(body: BodyInit | null | undefined): unknown {
  if (body === null || body === undefined) return undefined;
  if (typeof body !== "string") return body;
  try {
    return JSON.parse(body);
  } catch {
    return body;
  }
}

/** A tiny router for fetch in tests: real request shapes, no library-wide mocking framework. */
export function mockApi(routes: Route[]) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ url, method, body: parseBody(init?.body) });
    const route = routes.find((candidate) => candidate.match(url, init));
    if (route === undefined) {
      return new Response(JSON.stringify({ error: { code: "NOT_STUBBED", message: url } }), { status: 404 });
    }
    return new Response(JSON.stringify(route.payload), {
      status: route.status ?? 200, headers: { "Content-Type": "application/json" },
    });
  }));
  return calls;
}

/**
 * A stub answers its own path and no other. Matching by prefix let `/api/shelf` answer
 * `/api/shelf/{id}/removal-summary`, so a test could pass while the screen called something else
 * entirely. The query string is ignored, since that is where parameters live, not identity.
 */
const samePath = (path: string) => (url: string) => url.split("?")[0] === path.split("?")[0];

const route = (method: string) => (path: string, payload: unknown, status?: number): Route => ({
  match: (url, init) => samePath(path)(url) && (init?.method ?? "GET").toUpperCase() === method,
  payload, status,
});

export const get = route("GET");
export const post = route("POST");
export const del = route("DELETE");

type RouteType = Route;
export type { RouteType as Route };
