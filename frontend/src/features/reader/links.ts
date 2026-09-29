/** Keep the selected track when entering reading, changing units, or returning to Work Details. */
export function readerLink(unitId: string, workId: string, trackId?: string | null): string {
  const query = new URLSearchParams();
  if (workId) query.set("work", workId);
  if (trackId) query.set("track", trackId);
  return `/read/${unitId}${query.size ? `?${query}` : ""}`;
}
export function workLink(workId: string, trackId?: string | null): string {
  return workId ? `/works/${workId}${trackId ? `?${new URLSearchParams({ track: trackId })}` : ""}` : "/shelf";
}
