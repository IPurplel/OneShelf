import { useEffect, useRef } from "react";
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
  const panel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="confirm" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={panel}>
      <h2 className="display">{title}</h2>
      <p>{body}</p>
      {children}
      <div className="confirm__actions">
        <button type="button" className="button" onClick={onCancel}>{t("common.cancel")}</button>
        <button type="button" className="button button--primary" onClick={onConfirm}>{confirmLabel}</button>
      </div>
    </div>
  );
}
