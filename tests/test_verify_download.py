"""Audit instrument regressions; generated containers are not site fixtures."""
import importlib.util
import io
from pathlib import Path
import zipfile

import pytest
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / 'scratchpad' / 'verify_dl.py'
spec = importlib.util.spec_from_file_location('verify_dl', SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def test_pdf_with_only_signature_and_trailer_is_not_readable(tmp_path):
    path = tmp_path / 'fake.pdf'
    path.write_bytes(b'%PDF-1.4\n' + b'garbage' * 300 + b'\n%%EOF')
    assert not verifier.report_archive(path)


def test_zip_disguised_as_epub_is_not_readable(tmp_path):
    path = tmp_path / 'fake.epub'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('padding', b'x' * 2000)
    assert not verifier.report_archive(path)


def test_thumbnail_cbz_is_rejected(tmp_path):
    path = tmp_path / 'thumb.cbz'
    data = io.BytesIO()
    Image.new('RGB', (1, 1)).save(data, format='PNG')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('ComicInfo.xml', '<ComicInfo/>')
        z.writestr('001.png', data.getvalue())
    assert not verifier.report_archive(path)


def test_verification_settings_isolate_existing_data_and_environment(tmp_path, settings, monkeypatch):
    settings.ensure_dirs()
    sentinel = settings.output_dir / 'notes.txt'
    sentinel.write_text('keep')
    monkeypatch.setenv('MD_CONFIG_DIR', str(settings.config_dir))
    monkeypatch.setenv('MD_OUTPUT_DIR', str(settings.output_dir))
    monkeypatch.setenv('MD_BROWSER_DATA_DIR', str(settings.browser_profile_dir))
    before = settings.model_dump()
    first, run1 = verifier.create_run_settings(settings, tmp_path)
    second, run2 = verifier.create_run_settings(settings, tmp_path)
    assert run1 != run2
    for isolated, run in [(first, run1), (second, run2)]:
        assert isolated.db_path.is_relative_to(run)
        assert isolated.output_dir.is_relative_to(run)
        assert isolated.browser_profile_dir.is_relative_to(run)
        assert isolated.browser_cdp is None
        assert isolated.desync_port == 0
    assert settings.model_dump() == before
    assert sentinel.read_text() == 'keep'


def test_pdf_pages_are_rendered_and_counted(tmp_path):
    import pymupdf
    path = tmp_path / 'two-pages.pdf'
    with pymupdf.open() as doc:
        for text in ['First page', 'Second page']:
            page = doc.new_page()
            page.insert_text((72, 72), text)
        doc.save(path)
    result = verifier.inspect_artifact(path, expected_pages=2)
    assert result['passed'], result
    assert result['count'] == 2
    assert result['rendered_pages'] == 2
    assert not verifier.inspect_artifact(path, expected_pages=3)['passed']
    path.write_bytes(path.read_bytes()[:-40])
    assert not verifier.inspect_artifact(path)['passed']


def test_html_masquerading_as_book_is_rejected(tmp_path):
    path = tmp_path / 'book.pdf'
    path.write_bytes(b'<!doctype html><html>' + b'Access denied ' * 200)
    assert not verifier.report_archive(path)


def test_full_size_cbz_decodes_every_page_and_checks_count(tmp_path):
    path = tmp_path / 'chapter.cbz'
    data = io.BytesIO()
    Image.new('RGB', (800, 1200)).save(data, format='PNG')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('ComicInfo.xml', '<ComicInfo/>')
        z.writestr('001.png', data.getvalue())
        z.writestr('002.png', data.getvalue())
    result = verifier.inspect_artifact(path, expected_pages=2)
    assert result['passed'], result
    assert result['count'] == 2
    assert not verifier.inspect_artifact(path, expected_pages=3)['passed']
    with zipfile.ZipFile(path, 'a') as z:
        z.writestr('003.png', data.getvalue()[:50])
    assert not verifier.inspect_artifact(path)['passed']


def test_real_gutenberg_epub_opens_with_its_own_spine_layout():
    path = Path(__file__).parent / 'fixtures/books/gutenberg_frankenstein.epub'
    result = verifier.inspect_artifact(path)
    assert result['passed'], result
    assert result['count'] == 32
    assert result['unit'] == 'spine items'
    assert result['rendered_pages'] > 0


def test_epub_with_missing_spine_member_is_rejected(tmp_path):
    source = Path(__file__).parent / 'fixtures/books/gutenberg_frankenstein.epub'
    path = tmp_path / 'incomplete.epub'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(path, 'w') as dst:
        for member in src.infolist():
            if member.filename != 'OEBPS/3217704234512228407_84-h-10.htm.xhtml':
                dst.writestr(member, src.read(member.filename))
    assert not verifier.inspect_artifact(path)['passed']


def test_epub_with_empty_bodies_is_rejected(tmp_path):
    import xml.etree.ElementTree as ET
    source = Path(__file__).parent / 'fixtures/books/gutenberg_frankenstein.epub'
    path = tmp_path / 'empty.epub'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(path, 'w') as dst:
        for member in src.infolist():
            data = src.read(member.filename)
            if member.filename.endswith('.xhtml'):
                tree = ET.fromstring(data)
                body = tree.find('.//{*}body')
                if body is not None:
                    body.clear()
                data = ET.tostring(tree)
            dst.writestr(member, data)
    assert not verifier.inspect_artifact(path)['passed']


@pytest.mark.parametrize('timeout', [False, True])
async def test_failed_run_retains_evidence_without_touching_library(tmp_path, settings, monkeypatch, timeout):
    import argparse
    import json
    settings.ensure_dirs()
    marker = settings.output_dir / 'notes.txt'
    marker.write_text('existing user file')
    monkeypatch.setattr(verifier, 'settings', settings)

    async def failed_preview(*args):
        if timeout:
            import asyncio
            await asyncio.sleep(5)
        raise RuntimeError('reader unavailable')

    monkeypatch.setattr(verifier, 'preview_series', failed_preview)
    args = argparse.Namespace(url='https://example.test/book', out=tmp_path / 'audit',
                              language=None, chapter=None, format=None, timeout=0.01 if timeout else 5)
    assert await verifier.run(args) == 1
    report_path, = (tmp_path / 'audit').glob('run-*/evidence.json')
    report = json.loads(report_path.read_text())
    assert not report['passed']
    assert ('TimeoutError' if timeout else 'reader unavailable') in report['error']
    assert (report_path.parent / 'config/manga.db').exists()
    assert marker.read_text() == 'existing user file'
