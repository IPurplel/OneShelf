/**
 * OneShelf on a phone (asked for 2026-11-10): installable from the home network.
 *
 * Browsers only run a service worker on a secure origin (https, or localhost), so over plain http on the home
 * network the app still opens and can be added to the home screen, just without the offline page.
 */
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { registerOfflinePage } from "./pwa";

const root = resolve(__dirname, "../..");
const publicFile = (name: string) => readFileSync(resolve(root, "public", name));

afterEach(() => vi.unstubAllGlobals());

describe("the web app manifest", () => {
  const manifest = JSON.parse(publicFile("manifest.webmanifest").toString("utf-8"));

  it("opens full-screen at the start of the library", () => {
    expect(manifest).toMatchObject({ name: "OneShelf", start_url: "/", scope: "/", display: "standalone" });
  });

  it("offers icons of the sizes phones ask for, as files that really are that size", () => {
    const sizes = (purpose: string) => manifest.icons.filter((i: { purpose: string }) => i.purpose === purpose)
      .map((i: { sizes: string }) => i.sizes);
    expect(sizes("any")).toEqual(expect.arrayContaining(["192x192", "512x512"]));
    expect(sizes("maskable")).toContain("512x512");
    for (const icon of manifest.icons) {
      const png = publicFile(icon.src.replace(/^\//, ""));
      const [w, h] = icon.sizes.split("x").map(Number);
      // A PNG states its width and height at bytes 16 to 23.
      expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([w, h]);
    }
  });

  it("is linked from the page with credentials, so a signed-in remote visitor can fetch it", () => {
    const page = readFileSync(resolve(root, "index.html"), "utf-8");
    expect(page).toMatch(/<link rel="manifest" href="\/manifest\.webmanifest" crossorigin="use-credentials"/);
    expect(page).toMatch(/rel="apple-touch-icon" href="\/apple-touch-icon\.png"/);
    expect(page).toMatch(/name="apple-mobile-web-app-capable" content="yes"/);
    expect(readdirSync(resolve(root, "public"))).toContain("apple-touch-icon.png");
  });
});

describe("the service worker", () => {
  const worker = publicFile("sw.js").toString("utf-8");

  it("keeps nothing but the offline page, and only answers the opening of a page", () => {
    expect(worker).toContain('request.mode !== "navigate"');
    expect(worker.match(/cache\.add\(/g)).toHaveLength(1);
    expect(worker).not.toMatch(/cache\.put|addAll/);
  });

  it("has an offline page that says what is wrong in both languages", () => {
    const page = publicFile("offline.html").toString("utf-8");
    expect(page).toContain("OneShelf can't be reached");
    expect(page).toContain('lang="ar"');
  });
});

describe("registering the offline page", () => {
  it("registers when the origin is secure", async () => {
    const register = vi.fn(async () => ({}));
    vi.stubGlobal("isSecureContext", true);
    vi.stubGlobal("navigator", { serviceWorker: { register } });
    await registerOfflinePage();
    expect(register).toHaveBeenCalledWith("/sw.js", { scope: "/" });
  });

  it("does nothing over plain http, where the browser would refuse anyway", async () => {
    const register = vi.fn();
    vi.stubGlobal("isSecureContext", false);
    vi.stubGlobal("navigator", { serviceWorker: { register } });
    await registerOfflinePage();
    expect(register).not.toHaveBeenCalled();
  });

  it("does nothing where service workers do not exist, and never throws", async () => {
    vi.stubGlobal("isSecureContext", true);
    vi.stubGlobal("navigator", {});
    await expect(registerOfflinePage()).resolves.toBeUndefined();
    vi.stubGlobal("navigator", { serviceWorker: { register: async () => { throw new Error("blocked"); } } });
    await expect(registerOfflinePage()).resolves.toBeUndefined();
  });
});
