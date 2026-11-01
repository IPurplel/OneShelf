/** Keeps the bounded page band in memory so a page turn can reuse the bytes already fetched. */
export class PagePreloads {
  private blobs = new Map<number, string>();
  private failed = new Set<number>();
  private targets: number[] = [];
  private keep = new Set<number>();
  private active = new Map<number, AbortController>();
  private pausedFor: number | null = null;
  private disposed = false;
  private retryAt = 0;
  private concurrency: number;

  constructor(readonly unitId: string, private changed: () => void, concurrency = 3) {
    this.concurrency = concurrency;
  }

  url(page: number): string | undefined { return this.blobs.get(page); }
  pending(page: number): boolean { return this.active.has(page); }

  update(targets: number[], visible: number[], foregroundPage: number | null = null): void {
    this.targets = targets;
    this.keep = new Set([...targets, ...visible]);
    this.pausedFor = foregroundPage;
    for (const [page, url] of this.blobs) {
      if (!this.keep.has(page)) {
        URL.revokeObjectURL(url);
        this.blobs.delete(page);
      }
    }
    for (const page of this.failed) if (!this.keep.has(page)) this.failed.delete(page);
    for (const [page, controller] of this.active) {
      if (foregroundPage !== null || visible.includes(page) || !this.keep.has(page)) {
        this.active.delete(page);
        controller.abort();
        this.changed();
      }
    }
    this.fillSlots();
  }

  visibleLoaded(page: number): void {
    if (this.pausedFor === page) this.pausedFor = null;
    this.fillSlots();
  }

  private fillSlots(): void {
    if (this.disposed || this.pausedFor !== null || Date.now() < this.retryAt) return;
    for (const candidate of this.targets) {
      if (this.active.size >= this.concurrency) break;
      if (this.blobs.has(candidate) || this.failed.has(candidate) || this.active.has(candidate)) continue;
      const controller = new AbortController();
      this.active.set(candidate, controller);
      void this.load(candidate, controller);
    }
  }

  private async load(page: number, controller: AbortController): Promise<void> {
    try {
      const response = await fetch(`/api/reader/units/${this.unitId}/pages/${page}?prefetch=1`, {
        credentials: "same-origin", signal: controller.signal,
      });
      if (this.disposed || controller.signal.aborted) return;
      const retryAfter = Number(response.headers.get("Retry-After"));
      if (response.status === 503 && Number.isFinite(retryAfter) && retryAfter > 0) {
        this.retryAt = Date.now() + retryAfter * 1000;
        return;
      }
      if (!response.ok) throw new Error(`page ${page}: HTTP ${response.status}`);
      const blob = await response.blob();
      if (this.disposed || controller.signal.aborted || !this.keep.has(page)) return;
      this.blobs.set(page, URL.createObjectURL(blob));
    } catch {
      if (!controller.signal.aborted) this.failed.add(page);
    } finally {
      if (this.active.get(page) === controller) this.active.delete(page);
      if (!this.disposed) {
        this.changed();
        this.fillSlots();
      }
    }
  }

  dispose(): void {
    this.disposed = true;
    for (const controller of this.active.values()) controller.abort();
    this.active.clear();
    for (const url of this.blobs.values()) URL.revokeObjectURL(url);
    this.blobs.clear();
  }
}
