/** Master §13, §32.12: Use My Session — you sign in yourself, in a window OneShelf only relays. */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginSession } from "./LoginSession";
import { renderWithProviders } from "@/test/render";
import { del, mockApi, post } from "@/test/http";

const OPEN = { login_id: "l1", status: "open" };

afterEach(() => vi.unstubAllGlobals());

const start = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole("button", { name: /open the sign-in window/i }));
  return screen.findByRole("img", { name: /sign-in window/i });
};

describe("Use My Session", () => {
  it("says what it does and does not keep before opening anything", async () => {
    const calls = mockApi([post("/api/sources/oneshelf.example/login", OPEN)]);
    renderWithProviders(<LoginSession sourceId="oneshelf.example" sourceName="Example" onClose={() => {}} />);

    expect(screen.getByText(/you sign in yourself/i)).toBeInTheDocument();
    expect(screen.getByText(/never sees or stores your password/i)).toBeInTheDocument();
    expect(calls.length).toBe(0);
  });

  it("relays what you do in the window to the browser it opened", async () => {
    const calls = mockApi([post("/api/sources/oneshelf.example/login", OPEN),
                           post("/api/logins/l1/input", { login_id: "l1", status: "open" })]);
    const user = userEvent.setup();
    renderWithProviders(<LoginSession sourceId="oneshelf.example" sourceName="Example" onClose={() => {}} />);

    const frame = await start(user);
    await user.click(frame);
    await user.keyboard("a{Enter}");

    const inputs = calls.filter((c) => c.url === "/api/logins/l1/input").map((c) => c.body);
    expect(inputs.some((body) => (body as { type: string }).type === "click")).toBe(true);
    expect(inputs).toContainEqual({ type: "type", text: "a" });
    expect(inputs).toContainEqual({ type: "key", key: "Enter" });
  });

  it("captures the session only when you say you are signed in", async () => {
    const calls = mockApi([post("/api/sources/oneshelf.example/login", OPEN),
                           post("/api/logins/l1/complete", { login_id: "l1", outcome: "connected",
                                                             status: "connected" })]);
    const user = userEvent.setup();
    renderWithProviders(<LoginSession sourceId="oneshelf.example" sourceName="Example" onClose={() => {}} />);

    await start(user);
    await user.click(screen.getByRole("button", { name: /i am signed in/i }));

    expect(calls.some((c) => c.url === "/api/logins/l1/complete")).toBe(true);
    expect(await screen.findByText(/example is connected/i)).toBeInTheDocument();
  });

  it("says plainly when the site did not sign you in, and leaves the window open", async () => {
    mockApi([post("/api/sources/oneshelf.example/login", OPEN),
             post("/api/logins/l1/complete", { login_id: "l1", outcome: "not_logged_in", status: "open" })]);
    const user = userEvent.setup();
    renderWithProviders(<LoginSession sourceId="oneshelf.example" sourceName="Example" onClose={() => {}} />);

    await start(user);
    await user.click(screen.getByRole("button", { name: /i am signed in/i }));

    expect(await screen.findByText(/still does not look signed in/i)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /sign-in window/i })).toBeInTheDocument();
  });

  it("closes the window and keeps nothing when cancelled", async () => {
    const calls = mockApi([post("/api/sources/oneshelf.example/login", OPEN),
                           del("/api/logins/l1", { login_id: "l1", status: "cancelled" })]);
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderWithProviders(<LoginSession sourceId="oneshelf.example" sourceName="Example" onClose={onClose} />);

    await start(user);
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/logins/l1")).toBe(true);
    expect(onClose).toHaveBeenCalled();
  });
});
