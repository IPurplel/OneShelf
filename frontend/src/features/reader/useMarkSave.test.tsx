import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, it } from "vitest";

import { TestProviders } from "@/test/providers";
import { useMarkSave } from "./useMarkSave";

it("reuses one operation ID for retry and gives a new action a new ID", async () => {
  const ids: string[] = [];
  let fail = true;
  const action = async (operationId: string) => {
    ids.push(operationId);
    if (fail) throw new Error("response lost");
  };
  const { result } = renderHook(() => useMarkSave(), {
    wrapper: ({ children }: { children: ReactNode }) => <TestProviders>{children}</TestProviders>,
  });

  await act(async () => { await result.current.save(action); });
  expect(result.current.failure).not.toBeNull();
  fail = false;
  await act(async () => { await result.current.retry!(); });
  expect(ids[0]).toMatch(/^[0-9a-f-]{36}$/);
  expect(ids[1]).toBe(ids[0]);
  expect(result.current.failure).toBeNull();

  await act(async () => { await result.current.save(action); });
  expect(ids[2]).not.toBe(ids[0]);
});
