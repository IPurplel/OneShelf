/** Master §26.22: a PDF is navigated, searched through its own text layer, bookmarked and highlighted. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BookReader } from "./BookReader";
import { PdfView } from "./PdfView";
import { renderWithProviders } from "@/test/render";

const PAGES = [
  "Chapter One. The quiet begins here.",
  "Chapter Two. Rain on the window, and a long wait.",
];

vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerSrc: "" },
  getDocument: () => ({
    promise: Promise.resolve({
      numPages: PAGES.length,
      getPage: (number: number) => Promise.resolve({
        getViewport: () => ({ width: 100, height: 140 }),
        render: () => ({ promise: Promise.resolve() }),
        getTextContent: () => Promise.resolve({
          items: PAGES[number - 1]!.split(" ").map((word) => ({ str: `${word} ` })),
        }),
      }),
    }),
  }),
}));

type Call = { url: string; method: string; body: unknown };

function stubMarks(progress?: Record<string, unknown>): Call[] {
  const calls: Call[] = [];
  const marks: { bookmarks: unknown[]; highlights: unknown[] } = { bookmarks: [], highlights: [] };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ url, method, body });
    const json = (payload: unknown) => new Response(JSON.stringify(payload), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
    if (url.endsWith("/file")) {
      return new Response(new Uint8Array([37, 80, 68, 70]) as BodyInit,
                          { status: 200, headers: { "Content-Type": "application/pdf" } });
    }
    if (url.endsWith("/marks")) return json(marks);
    if (url.endsWith("/bookmarks") && method === "POST") {
      const made = { id: "b1", locator: body.locator, label: body.label, created_at: "2026-09-18T10:00:00+00:00" };
      marks.bookmarks.push(made);
      return json(made);
    }
    if (url.endsWith("/highlights") && method === "POST") {
      const made = { id: "h1", locator: body.locator, text: body.text, colour: "yellow",
                     created_at: "2026-09-18T10:00:00+00:00" };
      marks.highlights.push(made);
      return json(made);
    }
    return json(progress ?? { read_state: "unread", fraction: 0, locator: null, revision: 0 });
  }));
  return calls;
}

function selectWithin(element: HTMLElement, start: number, end: number) {
  const node = element.firstChild!;
  const range = document.createRange();
  range.setStart(node, start);
  range.setEnd(node, end);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
}

const view = () => (
  <PdfView unitId="u9" data={new ArrayBuffer(8)} workId="w1" onProgress={() => {}} onLeave={() => {}} />
);

afterEach(() => vi.unstubAllGlobals());

describe("Book Reader (PDF)", () => {
  it("moves through the pages it actually has", async () => {
    stubMarks();
    const user = userEvent.setup();
    renderWithProviders(view());

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/1 of 2/i));
    await user.click(screen.getByRole("button", { name: /next page/i }));
    expect(screen.getByRole("status")).toHaveTextContent(/2 of 2/i);
    await user.click(screen.getByRole("button", { name: /next page/i }));
    expect(screen.getByRole("status")).toHaveTextContent(/2 of 2/i);      // never past the end
  });

  it("searches the document's own text layer and goes to the page that matches", async () => {
    stubMarks();
    const user = userEvent.setup();
    renderWithProviders(view());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/1 of 2/i));

    await user.click(screen.getByRole("button", { name: /search/i }));
    const panel = await screen.findByRole("dialog", { name: /search/i });
    await user.type(within(panel).getByRole("searchbox"), "rain");
    const hit = await within(panel).findByRole("button", { name: /page 2/i });
    await user.click(hit);

    expect(screen.getByRole("status")).toHaveTextContent(/2 of 2/i);
  });

  it("keeps a bookmark and a highlight for the page being read", async () => {
    const calls = stubMarks();
    const user = userEvent.setup();
    renderWithProviders(view());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/1 of 2/i));

    await user.click(screen.getByRole("button", { name: /bookmark this place/i }));
    expect(calls.find((c) => c.url.endsWith("/bookmarks") && c.method === "POST")?.body)
      .toEqual({ locator: { page: 1 }, label: "Page 1" });

    await user.click(screen.getByRole("button", { name: /^highlight$/i }));
    const panel = await screen.findByRole("dialog", { name: /highlight/i });
    const passage = await within(panel).findByText(/the quiet begins/i);
    const start = passage.textContent!.indexOf("quiet");
    selectWithin(passage, start, start + "quiet".length);
    await user.click(within(panel).getByRole("button", { name: /keep this highlight/i }));

    expect(calls.find((c) => c.url.endsWith("/highlights") && c.method === "POST")?.body)
      .toMatchObject({ text: "quiet", locator: { page: 1, start } });
  });

  it("says when a document has no text to search", async () => {
    stubMarks();
    const user = userEvent.setup();
    renderWithProviders(view());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/1 of 2/i));

    await user.click(screen.getByRole("button", { name: /search/i }));
    const panel = await screen.findByRole("dialog", { name: /search/i });
    await user.type(within(panel).getByRole("searchbox"), "zzzz");
    expect(await within(panel).findByText(/nothing in this document matches/i)).toBeInTheDocument();
  });

  it("opens the document at the page it is given", async () => {
    stubMarks();
    renderWithProviders(
      <PdfView unitId="u9" data={new ArrayBuffer(8)} workId="w1" storedPage={2}
               onProgress={() => {}} onLeave={() => {}} />);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/2 of 2/i));
  });

  it("is given the page the library holds, through the Book Reader that renders it", async () => {
    stubMarks({ read_state: "partial", fraction: 0.5, locator: { page: 2 }, revision: 3 });
    renderWithProviders(<BookReader unitId="u9" format="pdf" workId="w1" />);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/2 of 2/i));
  });
});
