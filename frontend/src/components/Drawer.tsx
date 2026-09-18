import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

/**
 * A warm paper drawer (Master §32.19). It takes focus when it opens, returns it when it closes, and
 * closes on Escape — the reader's controls stay visible for as long as it is open (§26.3).
 */
export function Drawer({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const panel = useRef<HTMLDivElement | null>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    opener.current = document.activeElement;
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      (opener.current as HTMLElement | null)?.focus?.();
    };
  }, [onClose]);

  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={panel}>
      <header className="drawer__header">
        <h2 className="display">{title}</h2>
        <button type="button" className="drawer__close" onClick={onClose} aria-label="Close">×</button>
      </header>
      <div className="drawer__body">{children}</div>
    </div>
  );
}
