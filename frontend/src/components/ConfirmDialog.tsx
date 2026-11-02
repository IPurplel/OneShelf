import { ModalSurface } from "./ModalSurface";
import { useId, useRef } from "react";
import type { ReactNode } from "react";

import { useI18n } from "@/i18n/i18n";

/**
 * A destructive action explains exactly what will happen and what will remain untouched (Master §47,
 * §32.19). It is never a bare "are you sure?".
 */
export function ConfirmDialog({ title, body, confirmLabel, onConfirm, onCancel, children, danger = false, busy = false }: {
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
  /** The confirm button removes something that cannot be brought back from here. */
  danger?: boolean;
  busy?: boolean;
}) {
  const { t } = useI18n();
  const bodyId = useId();
  const cancel = useRef<HTMLButtonElement>(null);
  return (
    <ModalSurface className="confirm" title={title} onClose={onCancel} describedBy={bodyId}
                  initialFocus={danger ? cancel : undefined}>
      <h2 className="display">{title}</h2>
      <p id={bodyId}>{body}</p>
      {children}
      <div className="confirm__actions">
        <button ref={cancel} type="button" className="button" onClick={onCancel}>{t("common.cancel")}</button>
        <button type="button" className={`button ${danger ? "button--danger" : "button--primary"}`}
                disabled={busy} aria-busy={busy || undefined} onClick={onConfirm}>{confirmLabel}</button>
      </div>
    </ModalSurface>
  );
}
