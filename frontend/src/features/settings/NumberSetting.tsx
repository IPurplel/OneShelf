import { useId, useRef, useState } from "react";

import { ApiError } from "@/api/client";
import { useI18n } from "@/i18n/i18n";

/** A draft stays editable and visibly unsaved until its save succeeds. */
export function NumberSetting({ label, value, min, max, disabled = false, onSave }: {
  label: string; value: number; min: number; max: number; disabled?: boolean;
  onSave: (value: number) => void | Promise<void>;
}) {
  const { t } = useI18n();
  const id = useId();
  const [draft, setDraft] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [retryable, setRetryable] = useState(false);
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);

  const save = async () => {
    if (draft === null || pending.current || disabled) return;
    const number = Number(draft);
    if (draft.trim() === "" || !Number.isInteger(number) || number < min || number > max) {
      setProblem(t("settings.numberInvalid", { min, max }));
      setRetryable(false);
      return;
    }
    if (number === value) { setDraft(null); setProblem(null); setRetryable(false); return; }
    pending.current = true;
    setSaving(true);
    setProblem(null);
    setRetryable(false);
    try {
      await onSave(number);
      setDraft(null);
    } catch (error) {
      setProblem(t("settings.notSaved", { message: error instanceof ApiError ? error.message : t("state.offline") }));
      setRetryable(true);
    } finally {
      pending.current = false;
      setSaving(false);
    }
  };

  return <div>
    <label className="field__label" htmlFor={id}>{label}</label>
    <input id={id} type="number" className="field" min={min} max={max} step={1}
      value={draft ?? value} disabled={disabled || saving} aria-busy={saving}
      aria-invalid={problem !== null || undefined} aria-describedby={problem ? `${id}-error` : undefined}
      onChange={event => { setDraft(event.target.value); setProblem(null); setRetryable(false); }}
      onBlur={() => void save()} />
    {problem && <p id={`${id}-error`} className="notice notice--problem" role="alert">{problem}</p>}
    {retryable && <button type="button" className="button" disabled={disabled || saving} onClick={() => void save()}>
      {t("reader.retry")}
    </button>}
  </div>;
}
