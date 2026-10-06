import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { get, mockApi } from "@/test/http";
import { renderWithProviders } from "@/test/render";
import { HomeScreen } from "@/features/home/HomeScreen";
import { ShelfScreen } from "@/features/shelf/ShelfScreen";
import { FollowingScreen } from "@/features/following/FollowingScreen";
import { DownloadsScreen } from "@/features/downloads/DownloadsScreen";
import { SourcesScreen } from "@/features/sources/SourcesScreen";
import { StoragePanel } from "@/features/storage/StoragePanel";
import { BackupPanel } from "@/features/backup/BackupPanel";
import { WorkScreen } from "@/features/work/WorkScreen";
import { ExportWizard } from "@/features/export/ExportWizard";
import { NotificationsDrawer } from "@/features/notifications/NotificationsDrawer";

afterEach(() => vi.unstubAllGlobals());

it.each([
  ["Home", "/api/home", <HomeScreen />],
  ["Shelf", "/api/shelf", <ShelfScreen />],
  ["Following", "/api/follows", <FollowingScreen />],
  ["Downloads", "/api/downloads", <DownloadsScreen />],
  ["Sources", "/api/sources", <SourcesScreen />],
  ["Storage", "/api/storage", <StoragePanel />],
  ["Backups", "/api/backups", <BackupPanel />],
  ["Work Details", "/api/works/w1", <WorkScreen workId="w1" />],
  ["Export", "/api/works/w1", <ExportWizard workId="w1" onClose={() => {}} />],
  ["Notifications", "/api/notifications", <NotificationsDrawer onClose={() => {}} />],
] as const)("%s reports a failed initial load and can request it again", async (_name, path, view) => {
  const calls = mockApi([get(path, { error: { message: "Service unavailable" } }, 503)]);
  const user = userEvent.setup();
  renderWithProviders(view);
  expect((await screen.findAllByRole("alert")).some(alert => alert.textContent?.includes("Service unavailable")))
    .toBe(true);
  await user.click(screen.getAllByRole("button", { name: /try again/i })[0]!);
  await waitFor(() => expect(calls.filter(call => call.url.split("?")[0] === path && call.method === "GET").length)
    .toBeGreaterThan(1));
});
