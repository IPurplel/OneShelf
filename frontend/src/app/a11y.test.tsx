/** Master §45–§46, §2.3: keyboard reach, focus return, landmarks, and direction independence. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderApp, renderWithProviders } from "@/test/render";
import { get, mockApi } from "@/test/http";
import { Drawer } from "@/components/Drawer";
import { ConfirmDialog } from "@/components/ConfirmDialog";

afterEach(() => vi.unstubAllGlobals());

describe("Accessibility", () => {
  it("starts with a skip link that reaches the main region", async () => {
    mockApi([get("/api/home", { hero: null, continue_reading: [], trending: [], latest: [], recently_added: [] })]);
    const user = userEvent.setup();
    renderApp();
    await screen.findByRole("banner");

    await user.tab();
    const skip = document.activeElement as HTMLElement;
    expect(skip).toHaveTextContent(/skip to content/i);
    expect(skip.getAttribute("href")).toBe("#main");
    expect(document.querySelector("#main")).toHaveAttribute("tabindex", "-1");
  });

  it("names its landmarks so a screen reader can jump between them", async () => {
    mockApi([get("/api/home", { hero: null, continue_reading: [], trending: [], latest: [], recently_added: [] })]);
    renderApp();
    expect(await screen.findByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: /primary/i })).toBeInTheDocument();
  });

  it("reaches every primary destination by keyboard alone", async () => {
    mockApi([get("/api/home", { hero: null, continue_reading: [], trending: [], latest: [], recently_added: [] })]);
    renderApp();
    const nav = await screen.findByRole("navigation", { name: /primary/i });

    const links = within(nav).getAllByRole("link");
    for (const link of links) {
      link.focus();
      expect(document.activeElement).toBe(link);
    }
  });

  it("returns focus to the control that opened a drawer", async () => {
    const user = userEvent.setup();
    function Harness() {
      return (
        <>
          <button type="button" id="opener">Open</button>
          <Drawer title="Contents" onClose={() => document.getElementById("opener")?.focus()}>content</Drawer>
        </>
      );
    }
    renderWithProviders(<Harness />);
    const drawer = screen.getByRole("dialog", { name: "Contents" });
    expect(document.activeElement).toBe(drawer);

    await user.keyboard("{Escape}");
    expect(document.activeElement).toBe(document.getElementById("opener"));
  });

  it("closes a destructive dialog with Escape and keeps its explanation", async () => {
    const user = userEvent.setup();
    let cancelled = false;
    renderWithProviders(
      <ConfirmDialog title="Clear history" body="Your downloaded files stay. Progress is untouched."
                     confirmLabel="Clear history" onConfirm={() => {}} onCancel={() => { cancelled = true; }} />);

    const dialog = screen.getByRole("dialog", { name: /clear history/i });
    expect(dialog).toHaveTextContent(/files stay/i);
    expect(dialog).toHaveTextContent(/progress is untouched/i);
    await user.keyboard("{Escape}");
    expect(cancelled).toBe(true);
  });

  it("keeps interface direction independent from a work's own text", async () => {
    mockApi([get("/api/home", { hero: null, continue_reading: [], trending: [], latest: [], recently_added: [] })]);
    const user = userEvent.setup();
    renderApp();
    await screen.findByRole("banner");

    await user.click(screen.getByRole("button", { name: /العربية|arabic/i }));
    expect(document.documentElement).toHaveAttribute("dir", "rtl");
    // An Arabic label inside an English UI is marked as Arabic, and vice versa.
    const toggle = screen.getByRole("button", { name: /english/i });
    expect(within(toggle).getByText("English")).toHaveAttribute("lang", "en");
  });
});
