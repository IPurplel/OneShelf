#!/usr/bin/env python3
"""Shrink CBZ archives by re-encoding their pages to WebP.

    python tools/optimize_cbz.py /data/manga --dry-run
    python tools/optimize_cbz.py /data/manga --quality 84 --workers 4

This is a **lossy** trade. The downloader stores page images byte-for-byte on
purpose; this tool gives that up for roughly 30-60% less disk. Nothing is
overwritten unless the rebuilt archive verifies *and* comes out smaller, and
``--backup`` keeps the original beside it.

Design notes worth knowing before changing anything here:

* **Per-page best-of.** A well-optimised JPEG sometimes beats WebP. Any page
  that does not actually shrink keeps its original bytes, so an archive can
  never grow and quality is never spent for nothing.
* **Everything else is copied verbatim.** ``ComicInfo.xml`` carries series,
  numbering and reading direction; losing it would break Komga/Kavita. So
  non-image entries pass through untouched.
* **Stored, not deflated.** WebP is already compressed; deflating it again
  costs CPU to save nothing.
* **Verified before replacing.** The rebuilt archive is reopened, its page
  count compared, and every page decoded before the original is touched.
* **In memory.** Archives are rebuilt through ``io.BytesIO`` and land on disk
  once, as a single temp file replaced atomically.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import re
import shutil
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - dependency check
    sys.exit("Pillow is required:  pip install Pillow")

log = logging.getLogger("optimize-cbz")

SOURCE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
#: WebP cannot exceed this in either direction. Long-strip webtoon pages do,
#: and Pillow's error is opaque, so they are detected and left alone instead.
WEBP_MAX_DIMENSION = 16383


def natural_key(name: str) -> tuple:
    """Sort key that orders page10 after page9, not before it.

    Page order in a CBZ *is* filename order, so a plain lexical sort quietly
    reorders any chapter that reaches double digits.
    """
    return tuple(
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", name)
    )


@dataclass
class Result:
    path: Path
    before: int = 0
    after: int = 0
    pages: int = 0
    converted: int = 0
    skipped: bool = False
    error: str | None = None

    @property
    def saved(self) -> int:
        return max(self.before - self.after, 0)

    @property
    def percent(self) -> float:
        return (self.saved / self.before * 100) if self.before else 0.0


def encode_webp(data: bytes, quality: int) -> bytes | None:
    """Re-encode one image to WebP, or ``None`` if it should be left alone."""
    with Image.open(io.BytesIO(data)) as image:
        if getattr(image, "n_frames", 1) > 1:
            return None  # animated; converting would drop every frame but one
        if max(image.size) > WEBP_MAX_DIMENSION:
            return None  # long-strip page, beyond what the format allows

        # WebP takes RGB/RGBA only; CMYK scans and paletted PNGs must convert.
        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            prepared = image.convert("RGBA")
        elif image.mode != "RGB":
            prepared = image.convert("RGB")
        else:
            prepared = image

        buffer = io.BytesIO()
        # method=6 is the slowest, smallest setting; this runs once per file
        # and the result is kept forever, so the CPU is well spent.
        prepared.save(buffer, format="WEBP", quality=quality, method=6)
        return buffer.getvalue()


def rebuild(path: Path, quality: int) -> tuple[bytes, Result]:
    """Build an optimised copy of ``path`` in memory."""
    result = Result(path=path, before=path.stat().st_size)
    output = io.BytesIO()

    with zipfile.ZipFile(path) as source:
        names = [n for n in source.namelist() if not n.endswith("/")]
        images = sorted(
            (n for n in names if Path(n).suffix.lower() in SOURCE_SUFFIXES),
            key=natural_key,
        )
        others = [n for n in names if n not in set(images)]
        result.pages = len(images)

        with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as target:
            for name in images:
                data = source.read(name)
                encoded = encode_webp(data, quality)
                # Keep whichever is smaller: a good JPEG can beat WebP, and
                # spending quality to gain nothing is the worst of both.
                if encoded is not None and len(encoded) < len(data):
                    target.writestr(str(Path(name).with_suffix(".webp")), encoded)
                    result.converted += 1
                else:
                    target.writestr(name, data)

            # ComicInfo.xml and friends: metadata readers depend on.
            for name in others:
                target.writestr(name, source.read(name))

    result.after = output.tell()
    return output.getvalue(), result


def verify(blob: bytes, expected_pages: int) -> None:
    """Fail loudly if the rebuilt archive is not readable and complete."""
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        if archive.testzip() is not None:
            raise ValueError("rebuilt archive failed its CRC check")
        pages = [
            n for n in archive.namelist()
            if Path(n).suffix.lower() in SOURCE_SUFFIXES | {".webp"}
        ]
        if len(pages) != expected_pages:
            raise ValueError(f"page count changed: {expected_pages} -> {len(pages)}")
        for name in pages:
            with Image.open(io.BytesIO(archive.read(name))) as image:
                image.verify()


def process(path: Path, quality: int, dry_run: bool, backup: bool,
            min_saving: float) -> Result:
    try:
        blob, result = rebuild(path, quality)

        if result.pages == 0:
            result.skipped = True
            result.after = result.before
            result.error = "no images"
            return result

        if result.percent < min_saving:
            result.skipped = True
            result.after = result.before
            return result

        verify(blob, result.pages)
        if dry_run:
            return result

        # Land on disk once, then swap atomically: a crash mid-write leaves a
        # stray .tmp rather than a truncated archive that looks complete.
        temp = path.with_suffix(path.suffix + ".tmp")
        try:
            temp.write_bytes(blob)
            if backup:
                shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return result

    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
        return Result(path=path, before=path.stat().st_size if path.exists() else 0,
                      after=0, error=f"{type(exc).__name__}: {exc}")


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert CBZ page images to WebP to reclaim disk space.")
    parser.add_argument("path", type=Path, help="file or directory to scan")
    parser.add_argument("--quality", type=int, default=84,
                        help="WebP quality 1-100 (default: 84)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report savings without modifying anything")
    parser.add_argument("--backup", action="store_true",
                        help="keep the original alongside as .cbz.bak")
    parser.add_argument("--min-saving", type=float, default=5.0,
                        help="skip files saving less than this %% (default: 5)")
    parser.add_argument("--workers", type=int, default=max(os.cpu_count() // 2, 1),
                        help="archives processed in parallel")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not 1 <= args.quality <= 100:
        parser.error("--quality must be between 1 and 100")

    if args.path.is_file():
        files = [args.path]
    else:
        files = sorted(args.path.rglob("*.cbz"), key=lambda p: natural_key(str(p)))
    if not files:
        log.info("No .cbz files found under %s", args.path)
        return 0

    mode = "DRY RUN — nothing will be written" if args.dry_run else "converting"
    log.info("%d archive(s), quality %d, %s\n", len(files), args.quality, mode)

    results: list[Result] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process, path, args.quality, args.dry_run,
                        args.backup, args.min_saving): path
            for path in files
        }
        for done in as_completed(futures):
            result = done.result()
            results.append(result)
            if result.error and not result.skipped:
                log.warning("  FAILED  %-45s %s", result.path.name, result.error)
            elif result.skipped:
                log.info("  skipped %-45s (%s)", result.path.name,
                         result.error or f"saves only {result.percent:.1f}%")
            else:
                log.info("  ok      %-45s %8s -> %8s  (-%.1f%%, %d/%d pages)",
                         result.path.name, human(result.before), human(result.after),
                         result.percent, result.converted, result.pages)

    ok = [r for r in results if not r.error and not r.skipped]
    failed = [r for r in results if r.error and not r.skipped]
    skipped = [r for r in results if r.skipped]
    before = sum(r.before for r in ok)
    after = sum(r.after for r in ok)

    log.info("\n%s", "=" * 72)
    log.info("Processed : %d of %d archive(s)", len(ok), len(files))
    if skipped:
        log.info("Skipped   : %d (not worth converting)", len(skipped))
    if failed:
        log.info("Failed    : %d (originals untouched)", len(failed))
    log.info("Before    : %s", human(before))
    log.info("After     : %s", human(after))
    saved = before - after
    log.info("Saved     : %s  (%.1f%%)", human(saved),
             (saved / before * 100) if before else 0.0)
    if args.dry_run and ok:
        log.info("\nDry run — re-run without --dry-run to apply.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
