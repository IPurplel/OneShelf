import { useLayoutEffect, useRef } from "react";
import type { ReactNode } from "react";

/** Native modality makes the background inert; lifecycle and keyboard behavior are shared. */
export function ModalSurface({ title, className, children, onClose }: {
  title: string; className: string; children: ReactNode; onClose: () => void;
}) {
  const panel = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  useLayoutEffect(() => { close.current = onClose; }, [onClose]);

  useLayoutEffect(() => {
    const dialog = panel.current!;
    const opener = document.activeElement;
    dialog.showModal();
    dialog.focus();
    return () => {
      dialog.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  return <dialog ref={panel} className={`modal ${className}`} aria-label={title} aria-modal="true" tabIndex={-1}
    onCancel={event => { event.preventDefault(); close.current(); }}
    onKeyDown={event => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close.current();
      }
      if (event.key !== "Tab") return;
      const dialog = event.currentTarget;
      const controls = [...dialog.querySelectorAll<HTMLElement>(
        'button, a[href], input, select, textarea, [tabindex]',
      )].filter(element => element.tabIndex >= 0 && !element.matches(':disabled') && element.getClientRects().length > 0);
      const tabbable = controls.filter(element => {
        if (!(element instanceof HTMLInputElement) || element.type !== "radio" || !element.name) return true;
        const group = controls.filter((candidate): candidate is HTMLInputElement =>
          candidate instanceof HTMLInputElement && candidate.type === "radio" && candidate.name === element.name
          && candidate.form === element.form);
        return element === (group.find(candidate => candidate.checked) ?? group[0]);
      });
      const first = tabbable[0] ?? dialog;
      const last = tabbable.at(-1) ?? dialog;
      if (tabbable.length === 0 || (event.shiftKey && (document.activeElement === first || document.activeElement === dialog))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }}>
    {children}
  </dialog>;
}
