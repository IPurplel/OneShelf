import { useState } from "react";

import { useI18n } from "@/i18n/i18n";
import { newOperationId } from "@/lib/operationId";

/** Keep a failed bookmark or highlight available for one exact retry. */
export function useMarkSave() {
  const { t, errorText } = useI18n();
  const [failure, setFailure] = useState<string | null>(null);
  const [retry, setRetry] = useState<(() => Promise<void>) | null>(null);

  const save = async (action: (operationId: string) => Promise<void>, operationId?: string) => {
    setFailure(null);
    let id = operationId;
    try {
      id ??= newOperationId();
      await action(id);
      setRetry(null);
    } catch (error) {
      const reason = errorText(error);
      setFailure(t("book.markSaveFailed", { reason }));
      setRetry(() => () => save(action, id));
    }
  };

  return { failure, retry, save };
}

export function MarkSaveNotice({ failure, retry }: ReturnType<typeof useMarkSave>) {
  const { t } = useI18n();
  if (failure === null) return null;
  return <div className="notice notice--problem book__markProblem">
    <p role="alert">{failure}</p>
    {retry !== null && <button type="button" className="button"
      onClick={() => void retry()}>{t("book.retryMark")}</button>}
  </div>;
}
