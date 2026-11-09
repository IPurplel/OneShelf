import { useEffect, useRef, useState } from "react";

/**
 * How many covers may load at once. Covers queue behind a source's request rate, and a waiting image holds
 * one of the browser's six connections to OneShelf; three covers leave room for the live channel and for
 * whatever the person does next (a download sat 10.2 s unsent behind them, measured 2026-11-09).
 */
export const COVER_SLOTS = 3;

type Slot = { start: () => void; state: "waiting" | "loading" | "done" };

let loading = 0;
const queue: Slot[] = [];

function next(): void {
  while (loading < COVER_SLOTS && queue.length > 0) {
    const slot = queue.shift()!;
    slot.state = "loading";
    loading += 1;
    slot.start();
  }
}

/** Ask to load one cover. `start` runs when a slot is free; `release` frees it (or withdraws the request). */
export function requestCoverSlot(start: () => void): { release: () => void } {
  const slot: Slot = { start, state: "waiting" };
  queue.push(slot);
  next();
  return {
    release: () => {
      if (slot.state === "loading") {
        loading -= 1;
        slot.state = "done";
        next();
      } else if (slot.state === "waiting") {
        slot.state = "done";
        queue.splice(queue.indexOf(slot), 1);
      }
    },
  };
}

/** A cover slot for as long as `wanted` holds: `granted` once it may load, `release` when it has loaded. */
export function useCoverSlot(wanted: boolean): { granted: boolean; release: () => void } {
  const [granted, setGranted] = useState(false);
  const request = useRef<{ release: () => void } | null>(null);
  useEffect(() => {
    if (!wanted) return;
    const own = requestCoverSlot(() => setGranted(true));
    request.current = own;
    return () => {
      own.release();
      if (request.current === own) request.current = null;
      setGranted(false);
    };
  }, [wanted]);
  return { granted, release: () => request.current?.release() };
}
