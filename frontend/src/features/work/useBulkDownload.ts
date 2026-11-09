import { type Dispatch, type SetStateAction, useEffect, useState } from "react";

import { api } from "@/api/client";
import type { Unit } from "@/api/types";
import { useI18n } from "@/i18n/i18n";

/** A download batch accepts at most this many unit IDs; a longer catalogue is queued in several batches. */
const BATCH_UNITS = 2000;

export type BulkDownload = {
  /** Available units that are neither downloaded nor already asked for in this visit. */
  eligible: Unit[];
  requested: string[];
  setRequested: Dispatch<SetStateAction<string[]>>;
  queueing: boolean;
  problem: string | null;
  setProblem: (problem: string | null) => void;
  queueAll: () => Promise<void>;
};

/**
 * "Download all" for one track of a Work: shared by the button beside the title and the chapter list,
 * so both show the same request state (what was asked for stays asked for across tabs).
 */
export function useBulkDownload(workId: string, trackId: string | null, units: Unit[]): BulkDownload {
  const { errorText } = useI18n();
  const [problem, setProblem] = useState<string | null>(null);
  const [queueing, setQueueing] = useState(false);
  const [requested, setRequested] = useState<string[]>([]);
  useEffect(() => { setRequested([]); setProblem(null); }, [workId, trackId]);
  const eligible = units.filter(unit => unit.availability !== "unavailable" && !unit.downloaded
                                        && !requested.includes(unit.id));

  const queueAll = async () => {
    const ids = eligible.map(unit => unit.id);
    if (ids.length === 0) return;
    setProblem(null);
    setQueueing(true);
    try {
      for (let start = 0; start < ids.length; start += BATCH_UNITS) {
        const batch = ids.slice(start, start + BATCH_UNITS);
        await api.post("/api/downloads", { unit_ids: batch });
        setRequested(current => [...current, ...batch]);
      }
    } catch (error) {
      setProblem(errorText(error));
    } finally {
      setQueueing(false);
    }
  };

  return { eligible, requested, setRequested, queueing, problem, setProblem, queueAll };
}
