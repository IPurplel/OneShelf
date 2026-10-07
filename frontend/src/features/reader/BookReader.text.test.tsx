/** Text reading units (plugin API 1.2) in the Book Reader: same isolation, the unit's own direction. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BookReader } from "./BookReader";
import { textBook } from "./textUnit";
import type { TextUnitPayload } from "./textUnit";
import { renderWithProviders } from "@/test/render";

const english: TextUnitPayload = {
  reading_unit_id: "u1", origin: "online", title: "Chapter 7", language: "en", direction: "ltr",
  sections: [
    { title: "Chapter 7", html: "<h2>Chapter 7</h2><p>The lamp was still burning.</p>", characters: 36 },
    { title: null, html: "<p>She came back to the room.</p>", characters: 28 },
  ],
};

const arabic: TextUnitPayload = {
  reading_unit_id: "u2", origin: "local", title: "الفصل الأول", language: "ar", direction: "rtl",
  sections: [{ title: "الفصل الأول", html: "<p>كان المصباح ما يزال مضاءً.</p>", characters: 26 }],
};

type Call = { url: string; method: string; body: unknown };

function stubText(payload: TextUnitPayload | null, progress?: Record<string, unknown>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ url, method, body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
      status, headers: { "Content-Type": "application/json" },
    });
    if (url.endsWith("/text")) {
      return payload === null
        ? json({ error: { code: "TEXT_NOT_AVAILABLE", message: "The source returned no text." } }, 404)
        : json(payload);
    }
    if (url.endsWith("/marks")) return json({ bookmarks: [], highlights: [] });
    if (url.endsWith("/bookmarks") && method === "POST") {
      return json({ id: "b1", locator: { chapter: 1 }, label: "x", created_at: "2026-10-06T10:00:00+00:00" });
    }
    return json(progress ?? { read_state: "unread", fraction: 0, locator: null, revision: 0 });
  }));
  return calls;
}

function frame(): HTMLIFrameElement {
  return screen.getByTitle(/book content|محتوى/i) as HTMLIFrameElement;
}

afterEach(() => vi.unstubAllGlobals());

describe("Book Reader (text units)", () => {
  it("reads the unit's sections in the empty-sandbox frame and never asks for a file", async () => {
    const calls = stubText(english);
    renderWithProviders(<BookReader unitId="u1" format="text" workId="w1" />);
    await waitFor(() => expect(frame().getAttribute("srcdoc")).toContain("The lamp was still burning"));
    expect(frame().getAttribute("sandbox")).toBe("");
    expect(frame().getAttribute("srcdoc")).toContain("default-src 'none'");
    expect(frame().getAttribute("srcdoc")).toContain('dir="ltr"');
    expect(screen.getByRole("status")).toHaveTextContent("1 of 2");
    expect(calls.some(call => call.url.includes("/file"))).toBe(false);
    expect(calls.some(call => call.url === "/api/reader/units/u1/text")).toBe(true);
  });

  it("runs Arabic text right to left even when the interface is English", async () => {
    stubText(arabic);
    renderWithProviders(<BookReader unitId="u2" format="text" workId="w1" />, { language: "en" });
    await waitFor(() => expect(frame().getAttribute("srcdoc")).toContain("كان المصباح"));
    expect(frame().getAttribute("srcdoc")).toContain('dir="rtl"');
  });

  it("moves between sections and records progress as a share of the unit's characters", async () => {
    const calls = stubText(english);
    renderWithProviders(<BookReader unitId="u1" format="text" workId="w1" />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 of 2"));
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(frame().getAttribute("srcdoc")).toContain("She came back"));
    await waitFor(() => expect(calls.some(call => call.method === "POST" && call.url.endsWith("/progress")
      && (call.body as { fraction: number }).fraction === 1)).toBe(true), { timeout: 4000 });
  });

  it("resumes the section it was left on", async () => {
    stubText(english, { read_state: "partial", fraction: 0.5, locator: { chapter: 1 }, revision: 3 });
    renderWithProviders(<BookReader unitId="u1" format="text" workId="w1" />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("2 of 2"));
  });

  it("names sections without a heading after their unit in the contents", async () => {
    stubText(english);
    renderWithProviders(<BookReader unitId="u1" format="text" workId="w1" />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 of 2"));
    await userEvent.click(screen.getByRole("button", { name: /contents/i }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("Chapter 7 · 2")).toBeInTheDocument();
  });

  it("shows a recoverable error when the source has no text, and trying again asks again", async () => {
    const calls = stubText(null);
    renderWithProviders(<BookReader unitId="u1" format="text" workId="w1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The source returned no text.");
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(calls.filter(call => call.url.endsWith("/text"))).toHaveLength(2));
  });
});

describe("text unit as a book", () => {
  it("sanitises again on the client and drops every resource", async () => {
    const book = textBook({ ...english, sections: [{ title: null, characters: 1,
      html: "<p onclick='x()'>a<img src='https://tracker.example/p.png'><script>alert(1)</script></p>" }] });
    const chapter = await book.chapter(0);
    expect(chapter.html).not.toMatch(/onclick|script|tracker/);
    expect(chapter.text).toBe("a");
    expect(book.characters).toBe(1);
  });
});
