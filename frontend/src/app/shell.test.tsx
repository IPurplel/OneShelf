/** Master §32.1–32.2, §2.3: navigation, header controls, language and direction. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderApp } from "@/test/render";
import { get, mockApi } from "@/test/http";
import { setViewport } from "@/test/viewport";

describe("application shell", () => {
  it("offers exactly the ten primary destinations", async () => {
    renderApp();
    const nav = await screen.findByRole("navigation", { name: /primary/i });
    const names = within(nav).getAllByRole("link").map((link) => link.textContent?.trim());
    expect(names).toEqual(["Home", "Search", "Discover", "My Shelf", "Following", "Downloads", "Sources", "Settings", "History", "Statistics"]);
  });

  it("shows how many downloads are on their way beside Downloads, and nothing when none are", async () => {
    // A download started from Search used to vanish from view; the count says where it went (2026-11-09).
    mockApi([get("/api/downloads", { batches: [
      { batch_id: "b1", state: "active", pending: 2, completed: 1, failed: 0, canceled: 0, skipped: 0, counts: {} },
      { batch_id: "b2", state: "paused", pending: 1, completed: 0, failed: 0, canceled: 0, skipped: 0, counts: {} },
      { batch_id: "b3", state: "completed", pending: 0, completed: 4, failed: 0, canceled: 0, skipped: 0, counts: {} },
    ] })]);
    renderApp();
    const nav = await screen.findByRole("navigation", { name: /primary/i });
    const downloads = within(nav).getByRole("link", { name: /downloads/i });
    expect(await within(downloads).findByText("3")).toBeInTheDocument();
    expect(downloads).toHaveAccessibleName(/downloads.*3 on their way/i);
  });

  it("shows no download count when nothing is waiting", async () => {
    mockApi([get("/api/downloads", { batches: [{ batch_id: "b3", state: "completed", pending: 0, completed: 4, failed: 0, canceled: 0, skipped: 0, counts: {} }] })]);
    renderApp();
    const nav = await screen.findByRole("navigation", { name: /primary/i });
    const downloads = within(nav).getByRole("link", { name: /downloads/i });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(downloads.querySelector(".sidebar__badge")).toBeNull();
  });

  it("keeps notifications and needs attention in the header, not in the navigation", async () => {
    renderApp({ notifications: { unseen: 2, attention: 0 } });
    const header = await screen.findByRole("banner");
    expect(within(header).getByRole("button", { name: /notifications/i })).toBeInTheDocument();
    expect(within(header).queryByRole("button", { name: /needs attention/i })).not.toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: /primary/i });
    expect(within(nav).queryByText(/notifications/i)).not.toBeInTheDocument();
  });

  it("shows needs attention only when something is unresolved, with its count", async () => {
    renderApp({ notifications: { unseen: 3, attention: 2 } });
    const attention = await screen.findByRole("button", { name: /needs attention/i });
    expect(attention).toHaveTextContent("2");
  });

  it("has no profile or avatar anywhere", async () => {
    renderApp();
    await screen.findByRole("banner");
    expect(screen.queryByRole("button", { name: /profile|account|avatar|sign out/i })).not.toBeInTheDocument();
  });

  it("switches language and direction together, and the reader's text direction stays independent", async () => {
    const user = userEvent.setup();
    renderApp();
    await screen.findByRole("banner");
    expect(document.documentElement).toHaveAttribute("dir", "ltr");

    await user.click(screen.getByRole("button", { name: /العربية|arabic/i }));
    expect(document.documentElement).toHaveAttribute("dir", "rtl");
    expect(document.documentElement).toHaveAttribute("lang", "ar");
    expect(await screen.findByRole("link", { name: "الرئيسية" })).toBeInTheDocument();
  });

  it("marks the current destination for assistive technology", async () => {
    renderApp({ route: "/shelf" });
    const link = await screen.findByRole("link", { name: "My Shelf" });
    expect(link).toHaveAttribute("aria-current", "page");
  });
});

describe("mobile shell", () => {
  it("uses bottom navigation with four destinations plus More", async () => {
    setViewport("mobile");
    renderApp();
    const nav = await screen.findByRole("navigation", { name: /primary/i });
    expect(within(nav).getAllByRole("link").map((l) => l.textContent?.trim()))
      .toEqual(["Home", "Search", "Discover", "My Shelf"]);
    expect(within(nav).getByRole("button", { name: /more/i })).toBeInTheDocument();
    expect(screen.queryByText("Downloads")).not.toBeInTheDocument();
  });

  it("does not render the desktop sidebar as well", async () => {
    setViewport("mobile");
    renderApp();
    await screen.findByRole("navigation", { name: /primary/i });
    expect(screen.getAllByRole("navigation")).toHaveLength(1);
  });

  it.each(["/following", "/downloads", "/sources", "/settings/storage"])("marks More active on %s", async (route) => {
    setViewport("mobile");
    renderApp({ route });
    const more = await screen.findByRole("button", { name: "More" });
    expect(more).toHaveClass("is-active");
    expect(more).toHaveAttribute("aria-expanded", "false");
  });

  it.each([
    ["/downloads", "Downloads"],
    ["/sources", "Sources"],
    ["/settings/storage", "Settings"],
  ])("names the current section in the mobile header on %s", async (route, name) => {
    setViewport("mobile");
    renderApp({ route });
    const header = await screen.findByRole("banner");
    expect(within(header).getByText(name)).toBeVisible();
    expect(within(screen.getByRole("navigation", { name: /primary/i })).getByRole("button", { name: "More" }))
      .toBeInTheDocument();
  });

  it("translates the mobile current section when switching to Arabic", async () => {
    setViewport("mobile");
    const user = userEvent.setup();
    renderApp({ route: "/settings/storage" });
    await user.click(screen.getByRole("button", { name: /العربية|arabic/i }));
    expect(within(screen.getByRole("banner")).getByText("الإعدادات")).toBeVisible();
    expect(screen.getByRole("button", { name: "المزيد" })).toBeInTheDocument();
  });
});

describe("mobile More drawer", () => {
  it("marks the current destination as a non-link while other destinations remain links", async () => {
    setViewport("mobile");
    const user = userEvent.setup();
    renderApp({ route: "/settings/storage" });
    await user.click(screen.getByRole("button", { name: "More" }));
    const drawer = screen.getByRole("dialog", { name: "More" });
    expect(within(drawer).getAllByRole("link").map(link => link.textContent?.trim()))
      .toEqual(["Following", "Downloads", "Sources", "History", "Statistics"]);
    const current = within(drawer).getByText("Settings").closest("[aria-current]");
    expect(current).toHaveAttribute("aria-current", "page");
    expect(current).toHaveTextContent("Current");
  });

  it.each(["Downloads", "Sources", "Settings"])("navigates to %s and closes", async (name) => {
    setViewport("mobile");
    const user = userEvent.setup();
    renderApp();
    await user.click(screen.getByRole("button", { name: "More" }));
    const drawer = screen.getByRole("dialog", { name: "More" });
    expect(within(drawer).getAllByRole("link").map(link => link.textContent?.trim()))
      .toEqual(["Following", "Downloads", "Sources", "Settings", "History", "Statistics"]);
    expect(within(drawer).getByRole("button", { name: "Notifications" })).toBeInTheDocument();
    await user.click(within(drawer).getByRole("link", { name }));
    expect(screen.queryByRole("dialog", { name: "More" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 1, name })).toBeInTheDocument();
  });

  it("dismisses with Escape or Close and returns focus to More", async () => {
    setViewport("mobile");
    const user = userEvent.setup();
    renderApp();
    const more = screen.getByRole("button", { name: "More" });
    await user.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("dialog", { name: "More" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(more).toHaveFocus();
    await user.click(more);
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(more).toHaveFocus();
  });

  it("opens Notifications and returns focus to More when dismissed", async () => {
    setViewport("mobile");
    const user = userEvent.setup();
    renderApp();
    const more = screen.getByRole("button", { name: "More" });
    await user.click(more);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Notifications" }));
    expect(screen.getByRole("dialog", { name: "Notifications" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(more).toHaveFocus();
  });
});
