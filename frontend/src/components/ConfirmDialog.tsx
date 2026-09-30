import { ModalSurface } from "./ModalSurface";
import type { ReactNode } from "react";

import { useI18n } from "@/i18n/i18n";

/**
 * A destructive action explains exactly what will happen and what will remain untouched (Master §47,
 * §32.19). It is never a bare "are you sure?".
 */
export function ConfirmDialog({ title, body, confirmLabel, onConfirm, onCancel, children }: {
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <ModalSurface className="confirm" title={title} onClose={onCancel}>
      <h2 className="display">{title}</h2>
      <p>{body}</p>
      {children}
      <div className="confirm__actions">
        <button type="button" className="button" onClick={onCancel}>{t("common.cancel")}</button>
        <button type="button" className="button button--primary" onClick={onConfirm}>{confirmLabel}</button>
      </div>
    </ModalSurface>
  );
}
