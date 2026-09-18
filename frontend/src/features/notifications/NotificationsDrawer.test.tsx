/** Master §30, §32.2, §32.13, §44: an inbox on warm paper, and a filtered shortcut to real problems. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationsDrawer } from "./NotificationsDrawer";
import { renderWithProviders } from "@/test/render";
import { get, mockApi, post } from "@/test/http";

const ITEMS = {
  notifications: [
    { id: "n1", dedupe_key: "source-auth:mangadex", notification_class: "important", state: "active", seen: false,
      count: 1, title: "Reconnect required", summary: "MangaDex needs you to sign in again.",
      actions: ["reconnect"], payload: {}, created_at: "2026-09-18T09:00:00+00:00",
      updated_at: "2026-09-18T09:00:00+00:00" },
    { id: "n2", dedupe_key: "new-release:w1", notification_class: "important", state: "active", seen: true,
      count: 3, title: "New releases", summary: "Ch. 209–211", actions: ["open"], payload: {},
      created_at: "2026-09-18T08:00:00+00:00", updated_at: "2026-09-18T08:00:00+00:00" },
  ],
  needs_attention: 1,
};

afterEach(() => vi.unstubAllGlobals());

describe("Notifications", () => {
  it("lists what happened, newest first, marking what is unseen", async () => {
    mockApi([get("/api/notifications", ITEMS)]);
    renderWithProviders(<NotificationsDrawer onClose={() => {}} />);

    const drawer = await screen.findByRole("dialog", { name: /notifications/i });
    const items = within(drawer).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]!).getByText(/reconnect required/i)).toBeInTheDocument();
    expect(items[0]!.getAttribute("data-seen")).toBe("false");
    expect(within(items[1]!).getByText(/3/)).toBeInTheDocument();      // grouped count, not three rows
  });

  it("marks all seen and clears seen without touching reading state", async () => {
    const calls = mockApi([
      get("/api/notifications", ITEMS),
      post("/api/notifications/mark-all-seen", { updated: 1 }),
      post("/api/notifications/clear-seen", { removed: 1 }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<NotificationsDrawer onClose={() => {}} />);
    await screen.findByRole("dialog", { name: /notifications/i });

    await user.click(screen.getByRole("button", { name: /mark all as seen/i }));
    await user.click(screen.getByRole("button", { name: /clear seen/i }));
    expect(calls.some((c) => c.url === "/api/notifications/mark-all-seen")).toBe(true);
    expect(calls.some((c) => c.url === "/api/notifications/clear-seen")).toBe(true);
    expect(calls.every((c) => !c.url.includes("/reader/"))).toBe(true);   // INV-22
  });

  it("needs attention shows only unresolved actionable problems", async () => {
    mockApi([get("/api/notifications", { notifications: [ITEMS.notifications[0]], needs_attention: 1 })]);
    renderWithProviders(<NotificationsDrawer attentionOnly onClose={() => {}} />);

    const drawer = await screen.findByRole("dialog", { name: /needs attention/i });
    expect(within(drawer).getByText(/reconnect required/i)).toBeInTheDocument();
    expect(within(drawer).queryByText(/new releases/i)).not.toBeInTheDocument();
  });

  it("says plainly when there is nothing to report", async () => {
    mockApi([get("/api/notifications", { notifications: [], needs_attention: 0 })]);
    renderWithProviders(<NotificationsDrawer onClose={() => {}} />);
    expect(await screen.findByText(/nothing new/i)).toBeInTheDocument();
  });
});
