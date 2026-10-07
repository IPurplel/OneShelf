import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { TestProviders } from "@/test/providers";
import { useBookMarks } from "./useBookMarks";
import { useMarkSave } from "./useMarkSave";

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const wrapper = ({ children }: { children: ReactNode }) => <TestProviders>{children}</TestProviders>;

afterEach(() => vi.unstubAllGlobals());

it("reuses one operation ID for retry and gives a new action a new ID", async () => {
  const randomUUID = vi.fn()
    .mockReturnValueOnce("11111111-1111-4111-8111-111111111111")
    .mockReturnValueOnce("22222222-2222-4222-8222-222222222222");
  const getRandomValues = vi.fn();
  vi.stubGlobal("crypto", { randomUUID, getRandomValues });
  const ids: string[] = [];
  let fail = true;
  const action = async (operationId: string) => {
    ids.push(operationId);
    if (fail) throw new Error("response lost");
  };
  const { result } = renderHook(() => useMarkSave(), { wrapper });

  await act(async () => { await result.current.save(action); });
  expect(result.current.failure).not.toBeNull();
  fail = false;
  await act(async () => { await result.current.retry!(); });
  expect(ids[0]).toMatch(UUID_V4);
  expect(ids[1]).toBe(ids[0]);
  expect(result.current.failure).toBeNull();

  await act(async () => { await result.current.save(action); });
  expect(ids[2]).not.toBe(ids[0]);
  expect(randomUUID).toHaveBeenCalledTimes(2);
  expect(getRandomValues).not.toHaveBeenCalled();
});

it("saves bookmarks and highlights without randomUUID and keeps fallback IDs on retry", async () => {
  let seed = 1;
  vi.stubGlobal("crypto", {
    getRandomValues: (bytes: Uint8Array) => { bytes.fill(seed++); return bytes; },
  });
  const calls: { path: string; body: { operation_id: string } }[] = [];
  const attempts = { bookmarks: 0, highlights: 0 };
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/marks")) return Promise.resolve(Response.json({ bookmarks: [], highlights: [] }));
    const kind = path.endsWith("/bookmarks") ? "bookmarks" : "highlights";
    const body = JSON.parse(String(init?.body)) as { operation_id: string };
    calls.push({ path, body });
    attempts[kind] += 1;
    if (attempts[kind] === 1) return Promise.resolve(Response.json({ error: { message: "Response lost" } },
      { status: 503 }));
    return Promise.resolve(Response.json(kind === "bookmarks"
      ? { id: "b1", locator: { chapter: 0 }, label: "One", created_at: "" }
      : { id: `h${attempts.highlights}`, locator: { chapter: 0, start: 0, end: 4 },
          text: "same", colour: "yellow", created_at: "" }));
  }));
  const { result } = renderHook(() => ({ marks: useBookMarks("unit-1"), save: useMarkSave() }), { wrapper });

  await act(async () => { await result.current.save.save(id => result.current.marks.addBookmark(
    { chapter: 0 }, "One", id)); });
  expect(result.current.save.failure).not.toBeNull();
  await act(async () => { await result.current.save.retry!(); });
  expect(result.current.save.failure).toBeNull();

  const highlight = (id: string) => result.current.marks.addHighlight(
    { chapter: 0, start: 0, end: 4 }, "same", id);
  await act(async () => { await result.current.save.save(highlight); });
  expect(result.current.save.failure).not.toBeNull();
  await act(async () => { await result.current.save.retry!(); });
  await act(async () => { await result.current.save.save(highlight); });

  const bookmarkIds = calls.filter(call => call.path.endsWith("/bookmarks"))
    .map(call => call.body.operation_id);
  const highlightIds = calls.filter(call => call.path.endsWith("/highlights"))
    .map(call => call.body.operation_id);
  expect(bookmarkIds).toHaveLength(2);
  expect(bookmarkIds[0]).toMatch(UUID_V4);
  expect(bookmarkIds[1]).toBe(bookmarkIds[0]);
  expect(highlightIds).toHaveLength(3);
  expect(highlightIds[0]).toMatch(UUID_V4);
  expect(highlightIds[1]).toBe(highlightIds[0]);
  expect(highlightIds[2]).toMatch(UUID_V4);
  expect(highlightIds[2]).not.toBe(highlightIds[0]);
  expect(result.current.marks.bookmarks).toHaveLength(1);
  expect(result.current.marks.highlights).toHaveLength(2);
});
