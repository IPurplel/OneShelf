import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/render";
import { FilePicker } from "./FilePicker";

describe("Localized file picker", () => {
  it.each(["en", "ar"] as const)("keeps a native labeled input and shows the filename in %s", async (language) => {
    const choose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<FilePicker label={language === "en" ? "Choose a file" : "اختر ملفًا"}
      accept=".pdf" onChoose={choose} />, { language });
    const input = screen.getByLabelText(language === "en" ? "Choose a file" : "اختر ملفًا");
    expect(input).toHaveAttribute("type", "file");
    expect(screen.getByText(language === "en" ? "No file selected" : "لم يُحدَّد ملف")).toBeInTheDocument();
    const file = new File(["sample"], "قصة chapter.pdf", { type: "application/pdf" });
    await user.upload(input, file);
    expect(choose).toHaveBeenCalledWith(file);
    expect(screen.getByText("قصة chapter.pdf")).toBeInTheDocument();
  });
});
