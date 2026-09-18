import type { ReactNode } from "react";

/**
 * A row of works on a wooden shelf (Master §32.5). Library content gets shelf language; system screens
 * never do.
 */
export function Shelf({ title, children, id }: { title: string; children: ReactNode; id: string }) {
  return (
    <section className="shelf" aria-labelledby={`${id}-title`} role="region">
      <h2 className="shelf__title display" id={`${id}-title`}>{title}</h2>
      <div className="shelf__row">{children}</div>
      <div className="shelf__plank" aria-hidden="true" />
    </section>
  );
}
