/**
 * Covers wait in a source's queue for seconds, and each held one of the browser's six connections to
 * OneShelf meanwhile: a tap on Download sat 10.2 s in the browser before it was even sent (measured
 * 2026-11-09). At most three covers load at once, so the person's own requests always find a connection.
 */
import { describe, expect, it } from "vitest";

import { COVER_SLOTS, requestCoverSlot } from "./coverSlots";

describe("cover slots", () => {
  it("lets three covers load at once and starts the next as one finishes", () => {
    const granted: number[] = [];
    const requests = Array.from({ length: 5 }, (_, i) => requestCoverSlot(() => granted.push(i)));
    expect(COVER_SLOTS).toBe(3);
    expect(granted).toEqual([0, 1, 2]);
    requests[1]!.release();
    expect(granted).toEqual([0, 1, 2, 3]);
    requests[1]!.release();                                  // releasing twice frees nothing more
    expect(granted).toEqual([0, 1, 2, 3]);
    requests[4]!.release();                                  // a request given up while waiting never starts
    requests[0]!.release();
    expect(granted).toEqual([0, 1, 2, 3]);
    for (const request of requests) request.release();
  });
});
