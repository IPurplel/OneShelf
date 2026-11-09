import { useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { useLive } from "./live";

type Batches = { batches: { pending: number }[] };

/**
 * How many downloads are still on their way (queued, running, paused or waiting), for the count beside
 * Downloads. Re-read when a download changes, gathered so a busy batch's many job events cost one request.
 */
export function useActiveDownloads(): number {
  const [pending, setPending] = useState(0);
  const soon = useRef<ReturnType<typeof setTimeout> | null>(null);
  const read = useRef(() => {});
  read.current = () => {
    api.get<Batches>("/api/downloads")
      .then((data) => setPending(data.batches.reduce((total, batch) => total + (batch.pending ?? 0), 0)))
      .catch(() => {});            // a count is a convenience: when it cannot be read, it is simply not shown
  };
  useEffect(() => {
    read.current();
    return () => { if (soon.current !== null) clearTimeout(soon.current); };
  }, []);
  useLive(["download.batch", "download.job"], () => {
    if (soon.current !== null) return;
    soon.current = setTimeout(() => { soon.current = null; read.current(); }, 800);
  });
  return pending;
}
