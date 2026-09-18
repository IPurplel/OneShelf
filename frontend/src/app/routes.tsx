import type { ReactElement } from "react";

import { HomeScreen } from "@/features/home/HomeScreen";
import { DownloadsScreen } from "@/features/downloads/DownloadsScreen";
import { FollowingScreen } from "@/features/following/FollowingScreen";
import { SearchScreen } from "@/features/search/SearchScreen";
import { SettingsScreen } from "@/features/settings/SettingsScreen";
import { SourcesScreen } from "@/features/sources/SourcesScreen";
import { ShelfScreen } from "@/features/shelf/ShelfScreen";
import { WorkScreen } from "@/features/work/WorkScreen";
import { ReadRoute } from "@/features/reader/ReadRoute";

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
  { path: "/works/:workId", element: <WorkScreen /> },
  { path: "/read/:unitId", element: <ReadRoute /> },
];
