import type { ReactNode } from "react";
import { ModalSurface } from "./ModalSurface";
import { useI18n } from "@/i18n/i18n";

/**
 * A warm paper drawer (Master §32.19). It takes focus when it opens, returns it when it closes, and
 * closes on Escape — the reader's controls stay visible for as long as it is open (§26.3).
 */
export function Drawer({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const { t } = useI18n();

  return (
    <ModalSurface className="drawer" title={title} onClose={onClose}>
      <header className="drawer__header">
        <h2 className="display">{title}</h2>
        <button type="button" className="drawer__close" onClick={onClose} aria-label={t("common.close")}>×</button>
      </header>
      <div className="drawer__body">{children}</div>
    </ModalSurface>
  );
}
