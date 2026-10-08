import { useState } from "react";

import { useI18n } from "@/i18n/i18n";

/** Native file input with app-localized visible chrome and the native keyboard/file dialog behavior. */
export function FilePicker({ label, accept, disabled = false, onChoose }: {
  label: string; accept: string; disabled?: boolean; onChoose: (file: File) => void;
}) {
  const { t } = useI18n();
  const [filename, setFilename] = useState<string | null>(null);
  return <label className="field__label filepicker">
    {label}
    <span className="filepicker__control">
      <span className="button filepicker__button" aria-hidden="true">{t("file.choose")}</span>
      <bdi className="filepicker__name" dir="auto" aria-live="polite">{filename ?? t("file.none")}</bdi>
    </span>
    <input type="file" accept={accept} className="visually-hidden" disabled={disabled}
           aria-label={label} onChange={(event) => {
             const file = event.target.files?.[0];
             if (file) { setFilename(file.name); onChoose(file); }
           }} />
  </label>;
}
