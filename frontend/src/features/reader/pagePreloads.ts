/** Keeps the bounded page band in memory so a page turn can reuse the bytes already fetched. */
export class PagePreloads {
  private blobs = new Map<number, string>();
  private failed = new Set<number>();
  private targets: number[] = [];
  private keep = new Set<number>();
  private active: { page: number; controller: AbortController } | null = null;
  private pausedFor: number | null = null;
  private disposed = false;

  constructor(readonly unitId: string, private changed: () => void) {}

  url(page: number): string | undefined { return this.blobs.get(page); }
  pending(page: number): boolean { return this.active?.page === page; }

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
    if (this.active !== null && (foregroundPage !== null || visible.includes(this.active.page)
                                 || !this.keep.has(this.active.page))) {
      const active = this.active;
      this.active = null;
      active.controller.abort();
      this.changed();
    }
    this.startNext();
  }

  visibleLoaded(page: number): void {
    if (this.pausedFor === page) this.pausedFor = null;
  }

  private startNext(): void {
    if (this.disposed || this.active !== null || this.pausedFor !== null) return;
    const page = this.targets.find((candidate) => !this.blobs.has(candidate) && !this.failed.has(candidate));
    if (page === undefined) return;
    const controller = new AbortController();
    this.active = { page, controller };
    void this.load(page, controller);
  }

  private async load(page: number, controller: AbortController): Promise<void> {
    try {
      const response = await fetch(`/api/reader/units/${this.unitId}/pages/${page}?prefetch=1`, {
        credentials: "same-origin", signal: controller.signal,
      });
      if (!response.ok) throw new Error(`page ${page}: HTTP ${response.status}`);
      const blob = await response.blob();
      if (this.disposed || controller.signal.aborted || !this.keep.has(page)) return;
      this.blobs.set(page, URL.createObjectURL(blob));
    } catch {
      if (!controller.signal.aborted) this.failed.add(page);
    } finally {
      if (this.active?.controller === controller) this.active = null;
      if (!this.disposed) {
        this.changed();
        this.startNext();
      }
    }
  }

  dispose(): void {
    this.disposed = true;
    this.active?.controller.abort();
    for (const url of this.blobs.values()) URL.revokeObjectURL(url);
    this.blobs.clear();
  }
}
