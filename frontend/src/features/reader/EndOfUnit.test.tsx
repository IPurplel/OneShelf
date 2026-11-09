/** The end of a chapter can carry on to the next by itself, after a short countdown that can be stopped. */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useLocation } from "react-router-dom";

import { EndOfUnit } from "./ReaderScreen";
import { TestProviders } from "@/test/providers";

const UNIT = { id: "u1", title: "Chapter 1" } as never;
const NEXT = { id: "u2", title: "Chapter 2" } as never;

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderEnd(autoNext: boolean) {
  return render(
    <TestProviders>
      <EndOfUnit unit={UNIT} next={NEXT} workId="w1" trackId={null} onLeave={() => {}} autoNext={autoNext} />
      <Where />
    </TestProviders>);
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("End of a chapter", () => {
  it("carries on to the next chapter after a short countdown when asked to", () => {
    renderEnd(true);
    expect(screen.getByText(/next chapter in 5/i)).toBeInTheDocument();
    for (let second = 0; second < 5; second += 1) act(() => { vi.advanceTimersByTime(1000); });
    expect(screen.getByTestId("where")).toHaveTextContent("/read/u2");
  });

  it("stops when asked to stay", () => {
    renderEnd(true);
    act(() => { screen.getByRole("button", { name: /stay here/i }).click(); });
    act(() => { vi.advanceTimersByTime(8000); });
    expect(screen.getByTestId("where")).toHaveTextContent("/");
    expect(screen.queryByText(/next chapter in/i)).toBeNull();
  });

  it("waits for the reader when not asked to carry on", () => {
    renderEnd(false);
    act(() => { vi.advanceTimersByTime(8000); });
    expect(screen.getByTestId("where")).toHaveTextContent("/");
  });
});
