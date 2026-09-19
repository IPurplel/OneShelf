import { useState } from "react";
import type { ReactNode } from "react";

import { useI18n } from "@/i18n/i18n";

/**
 * Progressive disclosure (Master §45): what a reader needs to finish the task is on the page; the
 * technical knobs are here, one press away, never hidden and never in the way.
 */
export function Advanced({ label, children }: { label: string; children: ReactNode }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);

  return (
    <div className="panel__advanced">
      <button type="button" className="button" aria-expanded={open} onClick={() => setOpen((was) => !was)}>
        {open ? t("settings.advanced.hide", { label }) : t("settings.advanced.show", { label })}
      </button>
      {open && <div className="panel__advancedBody">{children}</div>}
    </div>
  );
}
