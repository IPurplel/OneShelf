import { afterEach, expect, it, vi } from "vitest";
import { PagePreloads } from "./pagePreloads";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it("pauses prefetch for Retry-After and resumes on later reader activity", async () => {
  vi.useFakeTimers();
  const requested: string[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    requested.push(String(input));
    return requested.length === 1
      ? new Response(null, { status: 503, headers: { "Retry-After": "120" } })
      : new Response(new Blob(["page"]));
  });
  const pool = new PagePreloads("unit", () => {}, 1);
  pool.update([2, 3], [1]);
  await vi.advanceTimersByTimeAsync(0);
  expect(requested).toHaveLength(1);
  pool.update([2, 3], [1]);
  await vi.advanceTimersByTimeAsync(119_000);
  expect(requested).toHaveLength(1);
  await vi.advanceTimersByTimeAsync(1_001);
  expect(requested).toHaveLength(1); // no unattended retry timer
  pool.update([2, 3], [1]);
  await vi.advanceTimersByTimeAsync(0);
  expect(requested).toHaveLength(3);
  expect(pool.url(2)).toBeDefined();
  expect(pool.url(3)).toBeDefined();
  pool.dispose();
});

it("fetches pages concurrently up to the concurrency limit", async () => {
  vi.useFakeTimers();
  const gates: (() => void)[] = [];
  vi.stubGlobal("fetch", (_input: RequestInfo | URL) =>
    new Promise<Response>((resolve) => {
      gates.push(() => resolve(new Response(new Blob(["page"]))));
    }),
  );
  const pool = new PagePreloads("unit", () => {}, 3);
  pool.update([1, 2, 3, 4, 5], []);
  await vi.advanceTimersByTimeAsync(0);
  expect(gates).toHaveLength(3);
  gates.forEach((g) => g());
  await vi.advanceTimersByTimeAsync(0);
  expect(gates).toHaveLength(5);
  gates.slice(3).forEach((g) => g());
  await vi.advanceTimersByTimeAsync(0);
  expect(pool.url(1)).toBeDefined();
  expect(pool.url(5)).toBeDefined();
  pool.dispose();
});
