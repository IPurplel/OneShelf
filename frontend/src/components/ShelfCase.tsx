import type { ReactNode } from "react";

/** The shared physical shelf for Home and My Shelf. Its timber layers carry no content. */
export function ShelfCase({ children, wrap = false }: { children: ReactNode; wrap?: boolean }) {
  return (
    <div className="shelf__case">
      <div className="shelf__deck" aria-hidden="true" />
      <div className={`shelf__row${wrap ? " shelf__row--wrap" : ""}`}>{children}</div>
      <div className="shelf__fascia" aria-hidden="true" />
    </div>
  );
}
