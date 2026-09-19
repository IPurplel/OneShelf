/** Master §36: one live channel, with polling when it cannot be opened, and a re-read on resync. */
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LiveProvider, useLive } from "./live";

type Handler = (event: { data: string }) => void;

class FakeEventSource {
  static last: FakeEventSource | null = null;
  static opened = 0;
  listeners = new Map<string, Handler[]>();
  onerror: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.last = this;
    FakeEventSource.opened += 1;
  }

  addEventListener(name: string, handler: Handler) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), handler]);
  }

  close() { this.closed = true; }

  emit(name: string, payload: unknown) {
    for (const handler of this.listeners.get(name) ?? []) handler({ data: JSON.stringify(payload) });
  }
}

function Screen({ onChange }: { onChange: () => void }) {
  const { connected } = useLive(["download.batch"], onChange);
  return <p>{connected ? "live" : "polling"}</p>;
}

beforeEach(() => {
  FakeEventSource.last = null;
  FakeEventSource.opened = 0;
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("The live channel", () => {
  it("tells a screen to re-read when the library says something changed", async () => {
    const onChange = vi.fn();
    render(<LiveProvider><Screen onChange={onChange} /></LiveProvider>);

    act(() => { FakeEventSource.last!.emit("hello", {}); });
    await waitFor(() => expect(screen.getByText("live")).toBeInTheDocument());

    act(() => { FakeEventSource.last!.emit("download.batch", { batch_id: "b1", queued: 3 }); });
    expect(onChange).toHaveBeenCalledTimes(1);

    // An event a screen did not ask for is not its business.
    act(() => { FakeEventSource.last!.emit("shelf.changed", { work_id: "w1" }); });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("falls back to polling while the stream is down, and stops once it is back", async () => {
    const onChange = vi.fn();
    render(<LiveProvider pollMs={1000}><Screen onChange={onChange} /></LiveProvider>);
    expect(screen.getByText("polling")).toBeInTheDocument();

    act(() => { vi.advanceTimersByTime(3200); });
    expect(onChange.mock.calls.length).toBeGreaterThanOrEqual(3);

    act(() => { FakeEventSource.last!.emit("hello", {}); });
    await waitFor(() => expect(screen.getByText("live")).toBeInTheDocument());

    const afterConnect = onChange.mock.calls.length;
    act(() => { vi.advanceTimersByTime(5000); });
    expect(onChange.mock.calls.length).toBe(afterConnect);      // no more polling while it is live
  });

  it("re-opens the stream after an error, and keeps the screens fed meanwhile", async () => {
    const onChange = vi.fn();
    render(<LiveProvider pollMs={1000}><Screen onChange={onChange} /></LiveProvider>);
    act(() => { FakeEventSource.last!.emit("hello", {}); });
    await waitFor(() => expect(screen.getByText("live")).toBeInTheDocument());

    act(() => { FakeEventSource.last!.onerror?.(); });
    expect(screen.getByText("polling")).toBeInTheDocument();
    expect(FakeEventSource.last!.closed).toBe(true);

    act(() => { vi.advanceTimersByTime(2500); });
    expect(FakeEventSource.opened).toBe(2);
  });

  it("re-reads on a resync rather than guessing what it missed", async () => {
    const onChange = vi.fn();
    render(<LiveProvider><Screen onChange={onChange} /></LiveProvider>);
    act(() => { FakeEventSource.last!.emit("hello", {}); });
    await waitFor(() => expect(screen.getByText("live")).toBeInTheDocument());

    act(() => { FakeEventSource.last!.emit("resync", { dropped: 12 }); });
    expect(onChange).toHaveBeenCalledTimes(1);                  // the screen re-reads
    expect(screen.getByText("polling")).toBeInTheDocument();    // and the stream is reopened
  });
});
