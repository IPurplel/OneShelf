import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ImportPanel } from "./ImportPanel";
import { renderWithProviders } from "@/test/render";
import { mockApi, post } from "@/test/http";

const REVIEW = {
  upload_id: "upload1", format: "cbz", suggested_title: "Chapter One", language: "en",
  page_count: 3, warnings: [], suggestions: [],
};

afterEach(() => vi.unstubAllGlobals());

describe("Import review", () => {
  it.each([
    ["en", "Choose a file", "Open work", "No file selected"],
    ["ar", "اختر ملفًا", "افتح العمل", "لم يُحدَّد ملف"],
  ] as const)("offers the imported work and clears the picker in %s", async (language, choose, open, empty) => {
    mockApi([post("/api/import/uploads", REVIEW), post("/api/import", { work_id: "w42" })]);
    const user = userEvent.setup();
    renderWithProviders(<ImportPanel />, { language });
    await user.upload(screen.getByLabelText(choose), new File(["archive"], "story.cbz"));
    await user.click(await screen.findByRole("button", { name: language === "en" ? "Import" : "استورد" }));

    expect(await screen.findByRole("link", { name: open })).toHaveAttribute("href", "/works/w42");
    expect(screen.getByText(empty)).toBeInTheDocument();
  });

  it("keeps an empty new-work title editable and explains what to fix", async () => {
    const calls = mockApi([post("/api/import/uploads", REVIEW), post("/api/import", { work_id: "w42" })]);
    const user = userEvent.setup();
    renderWithProviders(<ImportPanel />, { language: "en" });
    await user.upload(screen.getByLabelText("Choose a file"), new File(["archive"], "story.cbz"));
    const title = await screen.findByRole("textbox", { name: "Title" });
    await user.clear(title);
    await user.click(screen.getByRole("button", { name: "Import" }));

    expect(title).toHaveFocus();
    expect(title).toHaveAttribute("aria-invalid", "true");
    expect(title).toHaveAccessibleName("Title");
    expect(title).toHaveAccessibleDescription("Enter a title for the new work.");
    expect(screen.getByText("Enter a title for the new work.")).toBeInTheDocument();
    expect(calls.filter((call) => call.url === "/api/import")).toHaveLength(0);

    await user.type(title, "  A good title  ");
    await user.click(screen.getByRole("button", { name: "Import" }));
    await waitFor(() => expect(calls.find((call) => call.url === "/api/import")?.body)
      .toMatchObject({ title: "A good title" }));
  });
});
