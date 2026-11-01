/** Keeps a left-to-right value such as "134 KB" in its own order inside an Arabic sentence. */
export function isolate(text: string): string {
  return `⁨${text}⁩`;
}

/** Sizes people can read: 120 GB, not 128849018880. */
export function bytes(value: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}
