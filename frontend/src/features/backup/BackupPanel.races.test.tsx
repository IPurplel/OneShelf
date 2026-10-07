import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/render";
import { BackupPanel } from "./BackupPanel";

const backups = ["A", "B"].map((id) => ({ id, path: `/backups/${id}.zip`, kind: "library",
  created_at: "2026-10-07T00:00:00Z", verified_at: null, size_bytes: 1000, present: true }));
const preflight = (works: number) => ({ ok: true, compatible: true, kind: "library", schema_version: 16,
  counts: { works }, plugins: [], space_needed: 100, issues: [] });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const json = (value: unknown, status = 200) => Response.json(value, { status });

afterEach(() => vi.unstubAllGlobals());

it("keeps B's preflight after a closed A request resolves late", async () => {
  const a = deferred<Response>();
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    if (url === "/api/backups") return Promise.resolve(json({ backups, due: false, location_warning: null }));
    if (url === "/api/restore/preflight") {
      const path = JSON.parse(String(init?.body)).path as string;
      calls.push(path);
      return path.endsWith("A.zip") ? a.promise : Promise.resolve(json(preflight(222)));
    }
    if (url === "/api/restore") return Promise.resolve(json({}));
    return Promise.resolve(json({}));
  }));
  const user = userEvent.setup();
  renderWithProviders(<BackupPanel />);
  const rows = await screen.findAllByRole("listitem");
  await user.click(within(rows[0]!).getByRole("button", { name: "Restore" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
  await user.click(within(rows[1]!).getByRole("button", { name: "Restore" }));
  const dialog = screen.getByRole("dialog");
  expect(await within(dialog).findByText("222 works")).toBeInTheDocument();
  await act(async () => a.resolve(json(preflight(111))));
  expect(within(dialog).getByText("222 works")).toBeInTheDocument();
  expect(within(dialog).queryByText("111 works")).toBeNull();
  expect(calls).toEqual(["/backups/A.zip", "/backups/B.zip"]);
});

it("ignores a late A error while B is open", async () => {
  const a = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    if (url === "/api/backups") return Promise.resolve(json({ backups, due: false, location_warning: null }));
    if (url === "/api/restore/preflight")
      return JSON.parse(String(init?.body)).path.endsWith("A.zip") ? a.promise : Promise.resolve(json(preflight(222)));
    return Promise.resolve(json({}));
  }));
  const user = userEvent.setup();
  renderWithProviders(<BackupPanel />);
  const rows = await screen.findAllByRole("listitem");
  await user.click(within(rows[0]!).getByRole("button", { name: "Restore" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
  await user.click(within(rows[1]!).getByRole("button", { name: "Restore" }));
  const dialog = screen.getByRole("dialog");
  await within(dialog).findByText("222 works");
  await act(async () => a.resolve(json({ error: { message: "Old A failed" } }, 503)));
  expect(within(dialog).queryByText("Old A failed")).toBeNull();
  expect(within(dialog).getByText("222 works")).toBeInTheDocument();
});

it("ignores the first generation when the same archive is reopened", async () => {
  const old = deferred<Response>();
  let checks = 0;
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url === "/api/backups") return Promise.resolve(json({ backups, due: false, location_warning: null }));
    if (url === "/api/restore/preflight") return ++checks === 1 ? old.promise : Promise.resolve(json(preflight(222)));
    return Promise.resolve(json({}));
  }));
  const user = userEvent.setup();
  renderWithProviders(<BackupPanel />);
  const row = (await screen.findAllByRole("listitem"))[0]!;
  await user.click(within(row).getByRole("button", { name: "Restore" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
  await user.click(within(row).getByRole("button", { name: "Restore" }));
  const dialog = screen.getByRole("dialog");
  await within(dialog).findByText("222 works");
  await act(async () => old.resolve(json(preflight(111))));
  expect(within(dialog).getByText("222 works")).toBeInTheDocument();
  expect(within(dialog).queryByText("111 works")).toBeNull();
});

it("locks Replace restore during a pending request and unlocks after failure", async () => {
  const pending = deferred<Response>();
  let attempts = 0;
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url === "/api/backups") return Promise.resolve(json({ backups, due: false, location_warning: null }));
    if (url === "/api/restore/preflight") return Promise.resolve(json(preflight(2)));
    if (url === "/api/restore") return ++attempts === 1 ? pending.promise : Promise.resolve(json({}));
    return Promise.resolve(json({}));
  }));
  const user = userEvent.setup();
  renderWithProviders(<BackupPanel />);
  const rows = await screen.findAllByRole("listitem");
  await user.click(within(rows[0]!).getByRole("button", { name: "Restore" }));
  const dialog = screen.getByRole("dialog");
  await within(dialog).findByText("2 works");
  await user.click(within(dialog).getByRole("radio", { name: /replace my library/i }));
  const button = within(dialog).getByRole("button", { name: "Restore" });
  await user.dblClick(button);
  expect(attempts).toBe(1);
  expect(button).toBeDisabled();
  button.focus();
  await user.keyboard("{Enter}{Enter}");
  expect(attempts).toBe(1);
  await act(async () => pending.resolve(json({ error: { message: "Retry restore" } }, 503)));
  await waitFor(() => expect(button).toBeEnabled());
  await user.click(button);
  expect(attempts).toBe(2);
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});
