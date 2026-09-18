/** Master §32.1–32.2, §2.3: navigation, header controls, language and direction. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderApp } from "@/test/render";
import { setViewport } from "@/test/viewport";

describe("application shell", () => {
  it("offers exactly the seven primary destinations", async () => {
    renderApp();
    const nav = await screen.findByRole("navigation", { name: /primary/i });
    const names = within(nav).getAllByRole("link").map((link) => link.textContent?.trim());
    expect(names).toEqual(["Home", "Search", "My Shelf", "Following", "Downloads", "Sources", "Settings"]);
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
      .toEqual(["Home", "Search", "My Shelf", "Following"]);
    expect(within(nav).getByRole("button", { name: /more/i })).toBeInTheDocument();
    expect(screen.queryByText("Downloads")).not.toBeInTheDocument();
  });

  it("does not render the desktop sidebar as well", async () => {
    setViewport("mobile");
    renderApp();
    await screen.findByRole("navigation", { name: /primary/i });
    expect(screen.getAllByRole("navigation")).toHaveLength(1);
  });
});
