import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useI18n } from "@/i18n/i18n";
import { ShelfCase } from "@/components/ShelfCase";

/**
 * A row of face-out works on a wooden display shelf (Master §32.5).
 *
 * The plank sits directly under the covers; each work's title, type and progress read below it, so the
 * shelf looks like a shelf rather than a grid with decoration. Library content gets this treatment;
 * system screens never do.
 */
export function Shelf({ title, children, id, viewAllHref, recessed = false, compactRow = false }: {
  title: string;
  children: ReactNode;
  id: string;
  viewAllHref?: string;
  recessed?: boolean;
  compactRow?: boolean;
}) {
  const { t } = useI18n();
  const classes = ["shelf", recessed ? "shelf--recessed" : "", compactRow ? "shelf--compactRow" : ""]
    .filter(Boolean).join(" ");
  return (
    <section className={classes} aria-labelledby={`${id}-title`} role="region">
      <header className="shelf__head">
        <h2 className="shelf__title display" id={`${id}-title`}>{title}</h2>
        {viewAllHref && (
          <Link className="shelf__viewall" to={viewAllHref}>
            {t("home.viewAll")}<span aria-hidden="true"> →</span>
          </Link>
        )}
      </header>
      <ShelfCase>{children}</ShelfCase>
    </section>
  );
}
