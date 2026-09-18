import { useState } from "react";
import { Link } from "react-router-dom";

import type { Unit } from "@/api/types";
import { useI18n } from "@/i18n/i18n";
import { Drawer } from "@/components/Drawer";

type Filter = "all" | "unread" | "downloaded";

/** The contents drawer (Master §26.12): units, their states, light filters — never a separate page. */
export function ContentsDrawer({ units, currentId, workId, onClose }: {
  units: Unit[];
  currentId: string;
  workId: string;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [filter, setFilter] = useState<Filter>("all");

  const shown = units.filter((unit) => filter === "all"
    || (filter === "unread" && unit.read_state !== "read")
    || (filter === "downloaded" && unit.downloaded));

  return (
    <Drawer title={t("reader.contents")} onClose={onClose}>
      <div className="drawer__filters" role="group" aria-label={t("reader.contents")}>
        {(["all", "unread", "downloaded"] as Filter[]).map((candidate) => (
          <button key={candidate} type="button" className="chip" aria-pressed={filter === candidate}
                  onClick={() => setFilter(candidate)}>
            {t(`reader.filter.${candidate}` as const)}
          </button>
        ))}
      </div>
      <ul className="drawer__units">
        {shown.map((unit) => (
          <li key={unit.id}>
            <Link to={`/read/${unit.id}${workId ? `?work=${workId}` : ""}`}
                  aria-current={unit.id === currentId ? "true" : undefined}
                  className={unit.id === currentId ? "drawer__unit is-current" : "drawer__unit"}>
              <span className="drawer__unitTitle">{unit.title ?? unit.id}</span>
              <span className="drawer__unitState">
                {unit.read_state === "read" ? t("work.finished")
                  : unit.read_state === "partial" ? `${Math.round(unit.fraction * 100)}%` : t("work.unread")}
              </span>
              {unit.downloaded && <span className="drawer__unitBadge">{t("work.downloaded")}</span>}
            </Link>
          </li>
        ))}
      </ul>
    </Drawer>
  );
}
