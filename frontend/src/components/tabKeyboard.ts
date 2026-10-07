import type { KeyboardEvent } from "react";

/** Arrow keys follow DOM tab order in both locales; the browser handles visual RTL placement. */
export function handleTabKeys(event: KeyboardEvent<HTMLElement>) {
  const tab = (event.target as HTMLElement).closest<HTMLButtonElement>('[role="tab"]');
  if (tab === null || !event.currentTarget.contains(tab)) return;
  const tabs = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
    .filter((candidate) => !candidate.disabled);
  const current = tabs.indexOf(tab);
  if (current < 0 || tabs.length === 0) return;
  const vertical = event.currentTarget.getAttribute("aria-orientation") === "vertical";
  let next: number;
  if (event.key === "Home") next = 0;
  else if (event.key === "End") next = tabs.length - 1;
  else if (event.key === (vertical ? "ArrowDown" : "ArrowRight")) next = (current + 1) % tabs.length;
  else if (event.key === (vertical ? "ArrowUp" : "ArrowLeft")) next = (current - 1 + tabs.length) % tabs.length;
  else return;
  event.preventDefault();
  tabs[next]!.focus();
  tabs[next]!.click();
}
