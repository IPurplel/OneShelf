"""Preview -> real queue -> retained, inspected artifact in an isolated run.

    python scratchpad/verify_dl.py URL [--chapter N] [--format epub]
        [--language ar] [--out PARENT] [--timeout 600]

Every invocation creates a NEW child of --out (default .state/verification).
Config, database, browser profile and downloads are isolated there. Nothing is
removed, including on failure. --keep remains accepted for old callers.
Install requirements-dev.txt; run with PYTHONIOENCODING=utf-8 for Arabic logs.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
from pathlib import Path
import posixpath
import sys
import tempfile
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.desync import DesyncProxy  # noqa: E402
from app.fetcher import Fetcher  # noqa: E402
from app.models import JobStatus  # noqa: E402
from app.packager import verify_cbz, verify_epub, verify_file, verify_pdf  # noqa: E402
from app.queue import JobQueue, chapter_from_dict, preview_series, series_from_dict  # noqa: E402
from app.session import SessionManager  # noqa: E402

MIN_PAGE_WIDTH = 600


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--chapter', help='chapter number (default: first)')
    parser.add_argument('--format', choices=['epub', 'pdf', 'cbz', 'mobi', 'azw3'])
    parser.add_argument('--language')
    parser.add_argument('--out', type=Path, help='parent of a new retained run directory')
    parser.add_argument('--keep', action='store_true', help='compatibility option; all runs are retained')
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    return args


def create_run_settings(base, parent: Path):
    """Copy validated settings; assignment beats inherited MD_* storage paths."""
    parent = parent.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix='run-', dir=parent))
    isolated = base.model_copy(deep=True)
    isolated.config_dir = run_dir / 'config'
    isolated.output_dir = run_dir / 'downloads'
    isolated.browser_data_dir = run_dir / 'browser'
    isolated.browser_cdp = None  # an attached browser could carry account cookies
    isolated.desync_port = 0
    isolated._runtime_proxy = None
    isolated.ensure_dirs()
    return isolated, run_dir


def _epub_spine(path: Path) -> list[str]:
    """Follow container -> OPF -> spine; no fixed vendor directory assumption."""
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() or archive.read('mimetype') != b'application/epub+zip':
            raise ValueError('Invalid EPUB container')
        container = ET.fromstring(archive.read('META-INF/container.xml'))
        rootfile = container.find('.//{*}rootfile')
        if rootfile is None:
            raise ValueError('Missing EPUB rootfile')
        opf_path = rootfile.attrib['full-path']
        opf = ET.fromstring(archive.read(opf_path))
        manifest = {item.attrib['id']: item.attrib for item in opf.findall('.//{*}manifest/{*}item')}
        spine = []
        characters = 0
        for ref in opf.findall('.//{*}spine/{*}itemref'):
            item = manifest[ref.attrib['idref']]
            href = urlsplit(item['href'])
            if href.scheme or href.netloc:
                raise ValueError('Spine item is not stored in the EPUB')
            name = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), unquote(href.path)))
            doc = ET.fromstring(archive.read(name))
            body = doc.find('.//{*}body')
            if body is None:
                raise ValueError(f'No readable body in {name}')
            characters += len(' '.join(''.join(body.itertext()).split()))
            spine.append(name)
        if not spine or characters < 100:
            raise ValueError('Empty or insufficient readable prose in EPUB spine')
        # The app verifier is deliberately specific to its generated EPUBs.
        if 'OEBPS/chapter.xhtml' in spine and not verify_epub(path):
            raise ValueError('Generated EPUB failed app verifier')
        return spine


def inspect_artifact(path: Path, *, expected_pages: int | None = None) -> dict:
    """A pass requires opening content, not just recognizing a signature."""
    from PIL import Image

    path = path.resolve()
    result = {'path': str(path), 'passed': False, 'count': 0, 'unit': None}
    try:
        result['bytes'] = path.stat().st_size
        result['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        suffix = path.suffix.lower()
        if suffix == '.cbz':
            if not verify_cbz(path):
                raise ValueError('CBZ failed app verifier')
            dimensions = []
            with zipfile.ZipFile(path) as archive:
                if 'ComicInfo.xml' not in archive.namelist():
                    raise ValueError('Missing ComicInfo.xml')
                names = [n for n in archive.namelist() if n != 'ComicInfo.xml' and not n.endswith('/')]
                if names != sorted(names) or len(names) != len(set(names)):
                    raise ValueError('Duplicate or unordered CBZ pages')
                for name in names:
                    with Image.open(io.BytesIO(archive.read(name))) as img:
                        img.load()
                        dimensions.append([name, img.width, img.height])
                        if img.width < MIN_PAGE_WIDTH:
                            raise ValueError(f'Thumbnail-sized page: {name} ({img.width}x{img.height})')
            result.update(count=len(names), unit='pages', dimensions=dimensions)
        elif suffix in {'.epub', '.pdf'}:
            if suffix == '.pdf':
                if not verify_pdf(path):
                    raise ValueError('PDF failed app verifier')
            else:
                result['spine'] = _epub_spine(path)
            import pymupdf
            with pymupdf.open(path) as document:
                if document.needs_pass or document.page_count == 0:
                    raise ValueError('Document is locked or empty')
                for page in document:
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5))
                    if pixmap.width < 1 or pixmap.height < 1:
                        raise ValueError('Page did not render')
                result['rendered_pages'] = document.page_count
                result.update(count=document.page_count, unit='pages')
                if suffix == '.epub':
                    result.update(count=len(result['spine']), unit='spine items')
        else:
            if not verify_file(path):
                raise ValueError('File failed app verifier')
            raise ValueError('Signature checked only; manual reader verification required for this format')
        if expected_pages is not None and result['count'] != expected_pages:
            raise ValueError(f"Expected {expected_pages} pages, opened {result['count']}")
        result['passed'] = True
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    return result


def report_archive(path: Path) -> bool:
    result = inspect_artifact(path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result['passed']


async def run(args: argparse.Namespace) -> int:
    isolated, run_dir = create_run_settings(settings, args.out or ROOT / '.state' / 'verification')
    if args.language:
        isolated.language = args.language
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-7s %(name)s: %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler(run_dir / 'run.log', encoding='utf-8')])
    evidence = {'source_url': args.url, 'checked': datetime.now(timezone.utc).isoformat(),
                'run_dir': str(run_dir), 'passed': False}
    print(f'Isolated run: {run_dir}', flush=True)
    try:
        async with AsyncExitStack() as stack:
            if isolated.desync_enabled and not isolated.proxy:
                desync = DesyncProxy(port=0, split_at=isolated.desync_split, delay=isolated.desync_delay)
                isolated._runtime_proxy = await desync.start()
                stack.push_async_callback(desync.stop)
            db = Database(isolated.db_path)
            stack.push_async_callback(db.close)
            await db.connect()
            sessions = SessionManager(isolated, db)
            stack.push_async_callback(sessions.close)
            fetcher = Fetcher(isolated, sessions)
            stack.push_async_callback(fetcher.close)
            await fetcher.start()
            queue = JobQueue(isolated, db, sessions, fetcher)
            stack.push_async_callback(queue.shutdown)
            async with asyncio.timeout(args.timeout):
                preview = await preview_series(args.url, sessions, db)
                chapters = preview['chapters']
                evidence.update(adapter=preview['adapter'], title=preview['series']['title'],
                                listed_chapters=len(chapters))
                candidates = chapters
                if args.chapter is not None:
                    candidates = [c for c in candidates if c.get('number') is not None
                                  and float(c['number']) == float(args.chapter)]
                if args.format:
                    candidates = [c for c in candidates if c['title'].lower().endswith('.' + args.format)]
                if not candidates:
                    raise ValueError('No selectable chapter matches the requested number/format')
                wanted = candidates[0]
                evidence['chapter_url'] = wanted['url']
                job = await queue.create_job(series_from_dict(preview['series']), [chapter_from_dict(wanted)])
                while job.status in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED):
                    await asyncio.sleep(0.5)
                progress = next(iter(job.progress.values()))
                evidence.update(job_status=job.status.value, pages_expected=progress.pages_total,
                                pages_downloaded=progress.pages_done)
                if job.status != JobStatus.DONE or not progress.output_path:
                    raise ValueError(progress.error or f'Job ended {job.status.value} without a complete artifact')
                path = Path(progress.output_path)
                # Direct files count as one transport item; reader PDFs and CBZs
                # count actual source pages. Only compare like units.
                from app.adapters.registry import by_id
                adapter = by_id(preview['adapter'])(sessions)
                # Through the queue's helper, which awaits an adapter that
                # answers asynchronously -- some decide from the chapter page,
                # because a platform's theme cannot say whether a chapter is
                # pictures or prose.
                packaging = await JobQueue._packaging_for(
                    adapter, chapter_from_dict(wanted))
                expected = progress.pages_total if packaging in {'cbz', 'pdf'} else None
                artifact = inspect_artifact(path, expected_pages=expected)
                evidence.update(artifact=artifact, passed=artifact['passed'])
    except Exception as exc:
        evidence['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        (run_dir / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    print('PASS' if evidence['passed'] else 'FAIL')
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(run(parse_args())))
