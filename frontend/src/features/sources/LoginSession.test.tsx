/** Master §13, §32.12: Use My Session — you sign in yourself, in a window OneShelf only relays. */
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

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
  function pendingLogin() {
    let resolve!: (value: Response) => void;
    let reject!: (error: Error) => void;
    const response = new Promise<Response>((yes, no) => { resolve = yes; reject = no; });
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push(`${init?.method ?? "GET"} ${path}`);
      return path.endsWith("/login") ? response : Promise.resolve(Response.json({}));
    }));
    return { resolve, reject, calls };
  }

  it("deletes a login created after the dialog was closed", async () => {
    const pending = pendingLogin();
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderWithProviders(<LoginSession sourceId="oneshelf.example" sourceName="Example" onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: /open the sign-in window/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledOnce();
    pending.resolve(Response.json({ login_id: "late-1", status: "open" }));
    await waitFor(() => expect(pending.calls).toContain("DELETE /api/logins/late-1"));
    expect(pending.calls.filter(call => call === "DELETE /api/logins/late-1")).toHaveLength(1);
  });

  it("retries a transient cleanup failure for a late login without deleting a newer session", async () => {
    let answerFirst!: (response: Response) => void;
    const first = new Promise<Response>(resolve => { answerFirst = resolve; });
    const calls: string[] = [];
    let opens = 0;
    let oldDeletes = 0;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const method = init?.method ?? "GET";
      calls.push(`${method} ${path}`);
      if (path.endsWith("/login")) return ++opens === 1 ? first
        : Promise.resolve(Response.json({ login_id: "new-2", status: "open" }));
      if (path === "/api/logins/old-1" && method === "DELETE") return Promise.resolve(++oldDeletes === 1
        ? Response.json({ error: { message: "Temporary failure" } }, { status: 503 })
        : Response.json({ login_id: "old-1", status: "cancelled" }));
      return Promise.resolve(Response.json({}));
    }));
    function Host() {
      const [show, setShow] = useState(true);
      return <><button onClick={() => setShow(true)}>Reopen</button>
        {show && <LoginSession sourceId="oneshelf.example" sourceName="Example" onClose={() => setShow(false)} />}</>;
    }
    const user = userEvent.setup();
    renderWithProviders(<Host />);
    await user.click(screen.getByRole("button", { name: /open the sign-in window/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.click(screen.getByRole("button", { name: "Reopen" }));
    await start(user);
    answerFirst(Response.json({ login_id: "old-1", status: "open" }));
    await waitFor(() => expect(calls.filter(call => call === "DELETE /api/logins/old-1")).toHaveLength(2));
    expect(calls).not.toContain("DELETE /api/logins/new-2");
    expect(screen.getByRole("img", { name: /sign-in window/i })).toHaveAttribute("src", "/api/logins/new-2/frame?f=0");
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(calls.filter(call => call === "DELETE /api/logins/new-2")).toHaveLength(1));
  });

  it("does not delete a nonexistent login when startup rejects after closing", async () => {
    const pending = pendingLogin();
    const user = userEvent.setup();
    renderWithProviders(<LoginSession sourceId="oneshelf.example" sourceName="Example" onClose={() => {}} />);
    await user.click(screen.getByRole("button", { name: /open the sign-in window/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    await act(async () => { pending.reject(new Error("offline")); });
    expect(screen.queryByRole("img", { name: /sign-in window/i })).toBeNull();
    expect(pending.calls.some(call => call.startsWith("DELETE"))).toBe(false);
  });

  it("does not let a late first login affect a reopened dialog", async () => {
    let answerFirst!: (response: Response) => void;
    const first = new Promise<Response>(resolve => { answerFirst = resolve; });
    const calls: string[] = [];
    let opens = 0;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push(`${init?.method ?? "GET"} ${path}`);
      if (path.endsWith("/login")) return ++opens === 1 ? first
        : Promise.resolve(Response.json({ login_id: "new-2", status: "open" }));
      return Promise.resolve(Response.json({}));
    }));
    function Host() {
      const [show, setShow] = useState(true);
      return <><button onClick={() => setShow(true)}>Reopen</button>
        {show && <LoginSession sourceId="oneshelf.example" sourceName="Example" onClose={() => setShow(false)} />}</>;
    }
    const user = userEvent.setup();
    renderWithProviders(<Host />);
    await user.click(screen.getByRole("button", { name: /open the sign-in window/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.click(screen.getByRole("button", { name: "Reopen" }));
    await start(user);
    answerFirst(Response.json({ login_id: "old-1", status: "open" }));
    await waitFor(() => expect(calls).toContain("DELETE /api/logins/old-1"));
    expect(calls).not.toContain("DELETE /api/logins/new-2");
    expect(screen.getByRole("img", { name: /sign-in window/i })).toHaveAttribute("src", "/api/logins/new-2/frame?f=0");
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(calls.filter(call => call === "DELETE /api/logins/new-2")).toHaveLength(1));
  });
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
