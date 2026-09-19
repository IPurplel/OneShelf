import { useI18n } from "@/i18n/i18n";
import { bytes } from "@/lib/format";

export type RemovalSummary = {
  work_id: string;
  files: number;
  bytes: number;
  has_progress: boolean;
  is_followed: boolean;
};

/**
 * Removing a work from the Shelf (Master §22, §47, §23 / INV-10).
 *
 * The reader decides with the facts in front of them: how many files there are and how much room they
 * take, whether reading progress exists, whether the work is followed. Keeping the files and deleting
 * them are two separate, explicitly named actions — never a checkbox on a single "OK" — and what stays
 * behind is said as plainly as what goes, because removing from the Shelf is not unfollowing and is not
 * deleting progress.
 */
export function RemoveFromShelf({ title, summary, onKeep, onDelete, onCancel }: {
  title: string;
  summary: RemovalSummary;
  onKeep: () => void;
  onDelete: () => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();

  return (
    <div className="confirm confirm--wide" role="dialog" aria-modal="true" aria-label={t("shelf.remove.title")}>
      <h2 className="display">{t("shelf.remove.title")}</h2>
      <p>{t("shelf.remove.lede", { title })}</p>

      <section className="restore__step">
        <h3>{t("shelf.remove.goes")}</h3>
        <ul className="restore__counts">
          <li>{t("shelf.remove.entry")}</li>
        </ul>
      </section>

      <section className="restore__step">
        <h3>{t("shelf.remove.stays")}</h3>
        <ul className="restore__counts">
          {/* One file is one file: Arabic marks number and plural differently, and "1 ملفات" reads wrong. */}
          {summary.files === 1 && <li>{t("shelf.remove.file", { size: bytes(summary.bytes) })}</li>}
          {summary.files > 1 && (
            <li>{t("shelf.remove.files", { files: summary.files, size: bytes(summary.bytes) })}</li>
          )}
          {summary.has_progress && <li>{t("shelf.remove.progress")}</li>}
          {summary.is_followed && <li>{t("shelf.remove.follow")}</li>}
        </ul>
      </section>

      {summary.files > 0 && <p className="cards__meta">{t("shelf.remove.deleteNote")}</p>}

      <div className="confirm__actions">
        <button type="button" className="button" onClick={onCancel}>{t("common.cancel")}</button>
        {summary.files > 0 && (
          <button type="button" className="button" onClick={onDelete}>{t("shelf.remove.delete")}</button>
        )}
        <button type="button" className="button button--primary" onClick={onKeep}>
          {summary.files > 0 ? t("shelf.remove.keep") : t("shelf.remove.confirm")}
        </button>
      </div>
    </div>
  );
}
