import type { ReactElement } from "react";

import { HomeScreen } from "@/features/home/HomeScreen";
import { Placeholder } from "@/components/Placeholder";
import { DownloadsScreen } from "@/features/downloads/DownloadsScreen";
import { FollowingScreen } from "@/features/following/FollowingScreen";
import { SearchScreen } from "@/features/search/SearchScreen";
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
  { path: "/sources", element: <Placeholder titleKey="nav.sources" /> },
  { path: "/settings", element: <Placeholder titleKey="nav.settings" /> },
  { path: "/works/:workId", element: <WorkScreen /> },
  { path: "/read/:unitId", element: <ReadRoute /> },
];
