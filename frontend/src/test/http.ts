import { vi } from "vitest";

type Route = { match: (url: string, init?: RequestInit) => boolean; payload: unknown; status?: number };

/** A tiny router for fetch in tests: real request shapes, no library-wide mocking framework. */
export function mockApi(routes: Route[]) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
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

export const get = (path: string, payload: unknown, status?: number): Route => ({
  match: (url, init) => url.startsWith(path) && (init?.method ?? "GET").toUpperCase() === "GET",
  payload, status,
});

export const post = (path: string, payload: unknown, status?: number): Route => ({
  match: (url, init) => url.startsWith(path) && (init?.method ?? "GET").toUpperCase() === "POST",
  payload, status,
});

export const del = (path: string, payload: unknown, status?: number): Route => ({
  match: (url, init) => url.startsWith(path) && (init?.method ?? "GET").toUpperCase() === "DELETE",
  payload, status,
});

type RouteType = Route;
export type { RouteType as Route };
