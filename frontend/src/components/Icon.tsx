/** Line icons in one weight: quiet, literary, never emoji (Master §32). */
const PATHS: Record<string, string> = {
  home: "M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z",
  search: "M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14zm9 16-4.35-4.35",
  shelf: "M4 5h4v14H4zM10 5h4v14h-4zM16.5 6.2l3.4.9-3 12.1-3.4-.9z",
  following: "M5 4h11l3 3v13H5zM8 9h8M8 13h6",
  downloads: "M12 4v10m0 0 4-4m-4 4-4-4M5 19h14",
  sources: "M4 6h16M4 12h16M4 18h10",
  settings: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 3v2m0 14v2M5 5l1.5 1.5M17.5 17.5 19 19M3 12h2m14 0h2M5 19l1.5-1.5M17.5 6.5 19 5",
  bell: "M6 16V11a6 6 0 1 1 12 0v5l1.5 2.5h-15zM10 20a2 2 0 0 0 4 0",
  attention: "M12 4 3 19h18zM12 10v4m0 3v.5",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  close: "M6 6l12 12M18 6 6 18",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  list: "M4 6h16M4 12h16M4 18h16",
};

export function Icon({ name, size = 22 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={PATHS[name] ?? PATHS.more} />
    </svg>
  );
}
