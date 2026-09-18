import type { ReactElement } from "react";

import { HomeScreen } from "@/features/home/HomeScreen";
import { Placeholder } from "@/components/Placeholder";

export type AppRoute = { path: string; element: ReactElement };

export const routes: AppRoute[] = [
  { path: "/", element: <HomeScreen /> },
  { path: "/search", element: <Placeholder titleKey="nav.search" /> },
  { path: "/shelf", element: <Placeholder titleKey="nav.shelf" /> },
  { path: "/following", element: <Placeholder titleKey="nav.following" /> },
  { path: "/downloads", element: <Placeholder titleKey="nav.downloads" /> },
  { path: "/sources", element: <Placeholder titleKey="nav.sources" /> },
  { path: "/settings", element: <Placeholder titleKey="nav.settings" /> },
];
