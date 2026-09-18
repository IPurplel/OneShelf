import type { StringKey } from "@/i18n/strings";

export type Destination = { path: string; labelKey: StringKey; icon: string; mobile: boolean };

/** Master §32.1: exactly these seven. Notifications and Needs Attention live in the header. */
export const DESTINATIONS: Destination[] = [
  { path: "/", labelKey: "nav.home", icon: "home", mobile: true },
  { path: "/search", labelKey: "nav.search", icon: "search", mobile: true },
  { path: "/shelf", labelKey: "nav.shelf", icon: "shelf", mobile: true },
  { path: "/following", labelKey: "nav.following", icon: "following", mobile: true },
  { path: "/downloads", labelKey: "nav.downloads", icon: "downloads", mobile: false },
  { path: "/sources", labelKey: "nav.sources", icon: "sources", mobile: false },
  { path: "/settings", labelKey: "nav.settings", icon: "settings", mobile: false },
];
