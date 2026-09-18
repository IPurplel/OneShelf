import { useCallback, useEffect, useRef, useState } from "react";

import { Drawer } from "@/components/Drawer";
import { useI18n } from "@/i18n/i18n";

export type Selected = { text: string; start: number; end: number };

/**
 * Capturing a highlight (Master §26.22, §27, ledger K3).
 *
 * The chapter or page is rendered for reading inside an isolated frame, and OneShelf deliberately cannot
 * reach inside it — that isolation is the point. So a highlight is taken here instead, from the plain
 * text OneShelf itself extracted: text nodes only, never the document's own markup, in the app's own
 * document where a selection can be read. What is kept is the passage and where it was.
 *
 * The selection is remembered as it is made, because pressing a button can clear it.
 */
export function HighlightPane({ text, onKeep, onClose }: {
  text: string;
  onKeep: (selection: Selected) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const passage = useRef<HTMLParagraphElement | null>(null);
  const [chosen, setChosen] = useState<Selected | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const read = useCallback(() => {
    const selection = window.getSelection();
    const container = passage.current;
    if (selection === null || container === null || selection.rangeCount === 0 || selection.isCollapsed) return;
    const range = selection.getRangeAt(0);
    if (!container.contains(range.commonAncestorContainer)) return;
    const chosenText = range.toString();
    if (chosenText.trim() === "") return;
    const before = range.cloneRange();
    before.selectNodeContents(container);
    before.setEnd(range.startContainer, range.startOffset);
    const start = before.toString().length;
    setChosen({ text: chosenText, start, end: start + chosenText.length });
    setProblem(null);
  }, []);

  useEffect(() => {
    document.addEventListener("selectionchange", read);
    return () => document.removeEventListener("selectionchange", read);
  }, [read]);

  const keep = () => {
    read();
    const selection = chosen ?? latest(passage.current);
    if (selection === null) {
      setProblem(t("book.selectFirst"));
      return;
    }
    onKeep(selection);
  };

  return (
    <Drawer title={t("book.highlight")} onClose={onClose}>
      <p className="cards__meta">{t("book.highlightHelp")}</p>
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      <p className="book__passage" ref={passage} onMouseUp={read} onKeyUp={read}>{text}</p>
      {chosen !== null && <p className="cards__meta">{t("book.keeping", { text: chosen.text })}</p>}
      <div className="drawer__actions">
        <button type="button" className="button button--primary" onClick={keep}>{t("book.keepHighlight")}</button>
      </div>
    </Drawer>
  );
}

/** The selection as it stands right now, when no `selectionchange` was seen (a test, or a stale ref). */
function latest(container: HTMLElement | null): Selected | null {
  const selection = window.getSelection();
  if (selection === null || container === null || selection.rangeCount === 0 || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);
  if (!container.contains(range.commonAncestorContainer)) return null;
  const text = range.toString();
  if (text.trim() === "") return null;
  const before = range.cloneRange();
  before.selectNodeContents(container);
  before.setEnd(range.startContainer, range.startOffset);
  const start = before.toString().length;
  return { text, start, end: start + text.length };
}
