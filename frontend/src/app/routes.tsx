import { lazy, type ReactElement } from "react";

import { HomeScreen } from "@/features/home/HomeScreen";
import { SearchScreen } from "@/features/search/SearchScreen";
import { ShelfScreen } from "@/features/shelf/ShelfScreen";
import { WorkScreen } from "@/features/work/WorkScreen";

// The everyday screens load with the app; the rest arrive when first opened, so the first page a phone
// downloads is not every screen at once (the single bundle was 780 kB).
const DownloadsScreen = lazy(() => import("@/features/downloads/DownloadsScreen").then(m => ({ default: m.DownloadsScreen })));
const FirstRunScreen = lazy(() => import("@/features/firstrun/FirstRunScreen").then(m => ({ default: m.FirstRunScreen })));
const FollowingScreen = lazy(() => import("@/features/following/FollowingScreen").then(m => ({ default: m.FollowingScreen })));
const SettingsScreen = lazy(() => import("@/features/settings/SettingsScreen").then(m => ({ default: m.SettingsScreen })));
const SourcesScreen = lazy(() => import("@/features/sources/SourcesScreen").then(m => ({ default: m.SourcesScreen })));
const ReadRoute = lazy(() => import("@/features/reader/ReadRoute").then(m => ({ default: m.ReadRoute })));
const StatsScreen = lazy(() => import("@/features/stats/StatsScreen").then(m => ({ default: m.StatsScreen })));
const HistoryScreen = lazy(() => import("@/features/history/HistoryScreen").then(m => ({ default: m.HistoryScreen })));

export type AppRoute = { path: string; element: ReactElement };

export const routes: AppRoute[] = [
  { path: "/", element: <HomeScreen /> },
  { path: "/search", element: <SearchScreen /> },
  { path: "/shelf", element: <ShelfScreen /> },
  { path: "/following", element: <FollowingScreen /> },
  { path: "/downloads", element: <DownloadsScreen /> },
  { path: "/sources", element: <SourcesScreen /> },
  { path: "/settings", element: <SettingsScreen /> },
  { path: "/settings/:section", element: <SettingsScreen /> },
  { path: "/first-run", element: <FirstRunScreen /> },
  { path: "/history", element: <HistoryScreen /> },
  { path: "/stats", element: <StatsScreen /> },
  { path: "/works/:workId", element: <WorkScreen /> },
  { path: "/read/:unitId", element: <ReadRoute /> },
];
