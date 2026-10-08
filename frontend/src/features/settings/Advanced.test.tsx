import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Advanced } from "./Advanced";
import { renderWithProviders } from "@/test/render";

describe("Advanced disclosure", () => {
  it("names the Reader section once in both collapsed and expanded states", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Advanced label="Reader"><p>Technical options</p></Advanced>);
    const button = screen.getByRole("button", { name: "Show advanced Reader settings" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);
    expect(screen.getByRole("button", { name: "Hide advanced Reader settings" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Technical options")).toBeInTheDocument();
  });
});
