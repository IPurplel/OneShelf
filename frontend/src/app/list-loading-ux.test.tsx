import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/render";
import { ShelfScreen } from "@/features/shelf/ShelfScreen";
import { FollowingScreen } from "@/features/following/FollowingScreen";
import { DownloadsScreen } from "@/features/downloads/DownloadsScreen";
import { SourcesScreen } from "@/features/sources/SourcesScreen";
import { StoragePanel } from "@/features/storage/StoragePanel";
import { BackupPanel } from "@/features/backup/BackupPanel";

const cases = [
  { name: "Shelf", path: "/api/shelf", component: ShelfScreen, empty: { view: "all", entries: [] },
    emptyText: { en: "Nothing on this shelf", ar: "الرف" } },
  { name: "Following", path: "/api/follows", component: FollowingScreen, empty: { follows: [] },
    emptyText: { en: "You are not following anything yet.", ar: "لا تتابع شيئًا بعد." } },
  { name: "Downloads", path: "/api/downloads", component: DownloadsScreen, empty: { batches: [] },
    emptyText: { en: "Nothing has been downloaded", ar: "لم يُنزَّل" } },
  { name: "Sources", path: "/api/sources", component: SourcesScreen, empty: { sources: [] },
    emptyText: { en: "No sources", ar: "لا مصادر" } },
  { name: "Storage", path: "/api/storage", component: StoragePanel, empty: { roots: [] },
    emptyText: { en: "No storage locations yet.", ar: "لا توجد مواقع تخزين بعد." } },
  { name: "Backup", path: "/api/backups", component: BackupPanel,
    empty: { backups: [], due: false, location_warning: null },
    emptyText: { en: "No backups yet.", ar: "لا نسخ بعد." } },
] as const;

afterEach(() => vi.unstubAllGlobals());

describe("I-62 pending list states", () => {
  it.each(cases.flatMap(item => (["en", "ar"] as const).map(language => ({ ...item, language }))))(
    "$name in $language shows loading before its empty state and a retryable error", async (case_) => {
      let answer!: (response: Response) => void;
      const pending = new Promise<Response>(resolve => { answer = resolve; });
      vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
        const path = String(input).split("?")[0];
        return path === case_.path ? pending : Promise.resolve(Response.json({ configured: false, plugins: [] }));
      }));
      const Component = case_.component;
      const rendered = renderWithProviders(<Component />, { language: case_.language });
      expect(document.querySelector(".loading-state")).toHaveTextContent(
        case_.language === "en" ? "Loading" : "جارٍ التحميل");
      if (case_.name === "Following") expect(screen.queryByRole("button", { name: /Check all|تحقّق من الكل/i })).toBeNull();
      if (case_.name === "Backup" || case_.name === "Storage")
        expect(screen.getAllByRole("button").filter(button => button.classList.contains("button"))[0]).toBeDisabled();
      answer(Response.json(case_.empty));
      await waitFor(() => expect(document.querySelector(".loading-state")).toBeNull());
      expect(screen.getByText(new RegExp(case_.emptyText[case_.language]))).toBeInTheDocument();
      rendered.unmount();

      vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
        const path = String(input).split("?")[0];
        return Promise.resolve(path === case_.path
          ? Response.json({ error: { code: "SERVICE_UNAVAILABLE", message: "Service unavailable" } }, { status: 503 })
          : Response.json({ configured: false, plugins: [] }));
      }));
      renderWithProviders(<Component />, { language: case_.language });
      expect(await screen.findByRole("alert")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Try again|أعد المحاولة/i })).toBeInTheDocument();
      expect(document.querySelector(".loading-state")).toBeNull();
    });
});
