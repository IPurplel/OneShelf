import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useI18n } from "@/i18n/i18n";
import { bytes, isolate } from "@/lib/format";

export type Deleted = { deleted_files: number; freed_bytes?: number };

type Request = { title: string; body: string; run: () => Promise<Deleted> };

/**
 * One way to delete downloaded files everywhere they are offered: the same plain question, the same
 * danger button, and the same short report of what was freed (§47). Only files go; the work, its place
 * on the shelf and its reading progress stay.
 */
export function useFileDeletion(onDone: () => void) {
  const { t, tn, errorText } = useI18n();
  const [request, setRequest] = useState<Request | null>(null);
  const [busy, setBusy] = useState(false);

  const confirm = async () => {
    if (request === null) return;
    setBusy(true);
    try {
      const done = await request.run();
      const size = isolate(bytes(done.freed_bytes ?? 0));
      toast.success(tn("files.deleted", done.deleted_files, { size }));
      onDone();
    } catch (error) {
      toast.error(errorText(error));
    } finally {
      setBusy(false);
      setRequest(null);
    }
  };

  const dialog = request === null ? null : (
    <ConfirmDialog danger busy={busy} title={request.title} body={request.body}
                   confirmLabel={t("files.delete.confirm")}
                   onCancel={() => { if (!busy) setRequest(null); }} onConfirm={() => void confirm()} />
  );

  return { ask: setRequest, dialog };
}
