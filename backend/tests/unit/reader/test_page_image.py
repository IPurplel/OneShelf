"""The reader accepts safe static SVG pages as raster bytes, never as active content."""
import asyncio
import base64
import io
import os
import sys

import pytest
from PIL import Image


linux_worker = pytest.mark.skipif(sys.platform != "linux", reason="SVG worker requires Linux OS limits")


def normalize(data):
    from oneshelf.reader.page_image import normalize_page_image
    return asyncio.run(normalize_page_image(data))


def svg(content, **attributes):
    attrs = {"width": "20", "height": "20", **attributes}
    fields = " ".join(f'{key}="{value}"' for key, value in attrs.items())
    return f'<svg xmlns="http://www.w3.org/2000/svg" {fields}>{content}</svg>'.encode()


def test_raster_bytes_pass_through_unchanged():
    data = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(data, format="PNG")
    assert normalize(data.getvalue()) == data.getvalue()


@linux_worker
def test_svg_embedded_jpeg_keeps_vector_overlay_and_clip():
    jpeg = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(jpeg, format="JPEG")
    payload = base64.b64encode(jpeg.getvalue()).decode()
    data = svg(f'<defs><clipPath id="left"><rect width="10" height="20"/></clipPath></defs>'
               f'<image width="20" height="20" href="data:image/jpeg;base64,{payload}"/>'
               '<g clip-path="url(#left)"><rect width="20" height="20" fill="blue"/></g>')
    result = normalize(data)
    assert result.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (40, 40)
        rgb = image.convert("RGB")
        assert rgb.getpixel((5, 20)) == (0, 0, 255)
        red = rgb.getpixel((35, 20))
        assert red[0] > 240 and red[1] < 10 and red[2] < 10


@pytest.mark.parametrize(("content", "message"), [
    ('<script>alert(1)</script>', 'unsupported SVG element'),
    ('<foreignObject/>', 'unsupported SVG element'),
    ('<rect onclick="alert(1)"/>', 'event handler'),
    ('<image href="https://example.com/private.png"/>', 'external reference'),
    ('<image href="file:///etc/passwd"/>', 'external reference'),
    ('<use href="data:image/svg+xml;base64,PHN2Zy8+"/>', 'data reference'),
    ('<rect fill="url(https://example.com/paint.svg)"/>', 'external reference'),
    ('<style>@import "https://example.com/style.css";</style>', 'unsupported SVG element'),
    ('<rect style="background:blue"/>', 'unsupported SVG style'),
    ('<g xml:base="file:///tmp/"/>', 'base URI'),
    ('<?xml-stylesheet href="https://example.com/x.css"?>', 'processing instruction'),
])
@linux_worker
def test_svg_rejects_active_or_external_content(content, message):
    with pytest.raises(ValueError, match=message):
        normalize(svg(content))


@linux_worker
def test_svg_rejects_xml_entities():
    data = b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">&x;</svg>'
    with pytest.raises(ValueError, match="DTD|entities"):
        normalize(data)


@pytest.mark.parametrize("data", [b'<svg', b'<?xml version="1.0"?><svg>'])
@linux_worker
def test_svg_rejects_malformed_xml(data):
    with pytest.raises(ValueError, match="malformed SVG"):
        normalize(data)


@linux_worker
def test_svg_rejects_oversized_dimensions():
    with pytest.raises(ValueError, match="pixel limit"):
        normalize(svg('<rect width="20000" height="20000"/>', width="20000", height="20000"))


@linux_worker
def test_svg_accepts_bom_and_xml_declaration():
    data = b'\xef\xbb\xbf<?xml version="1.0"?>' + svg('<rect width="20" height="20" fill="blue"/>')
    assert normalize(data).startswith(b"\x89PNG")


@pytest.mark.parametrize("reference", ["data:image/svg+xml;base64,PHN2Zy8+", "data:text/html;base64,eA==",
                                       "data:image/jpeg;base64,not-valid!", "data:image/png;base64,eA=="])
@linux_worker
def test_svg_rejects_invalid_embedded_raster(reference):
    with pytest.raises(ValueError):
        normalize(svg(f'<image href="{reference}"/>'))


def test_svg_refuses_unsupported_platform_but_keeps_raster_reading(monkeypatch):
    from oneshelf.reader import page_image
    monkeypatch.setattr(page_image.sys, "platform", "win32")
    with pytest.raises(ValueError, match="bounded Linux worker"):
        normalize(svg('<rect/>'))
    assert normalize(b"raster bytes") == b"raster bytes"


@pytest.mark.parametrize("cancel", [False, True])
@linux_worker
def test_hung_renderer_is_killed_and_its_slot_released(tmp_path, monkeypatch, cancel):
    from oneshelf.reader import page_image
    pid_file = tmp_path / "worker.pid"
    worker = tmp_path / "slow_worker.py"
    worker.write_text("import os, pathlib, sys, time\n"
                      f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
                      "sys.stdin.buffer.read()\ntime.sleep(60)\n")
    original_path = page_image.__file__
    monkeypatch.setattr(page_image, "__file__", str(worker))
    monkeypatch.setattr(page_image, "WALL_SECONDS", 1)

    async def scenario():
        task = asyncio.create_task(page_image.normalize_page_image(svg('<rect/>')))
        async with asyncio.timeout(5):
            while not pid_file.exists():
                await asyncio.sleep(0.01)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(ValueError, match="time limit"):
                await task
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)
        monkeypatch.setattr(page_image, "__file__", original_path)
        monkeypatch.setattr(page_image, "WALL_SECONDS", 8)
        assert (await page_image.normalize_page_image(svg('<rect/>'))).startswith(b"\x89PNG")

    asyncio.run(scenario())


@linux_worker
def test_static_presentation_styles_and_symbol_overflow_preserve_pixels():
    data = svg('<defs><symbol id="square" overflow="visible">'
               '<path d="M0 0H20V20H0Z" style="stroke:none"/></symbol></defs>'
               '<g fill="red" style="fill:#000;fill-opacity:1">'
               '<use href="#square"/></g>')
    with Image.open(io.BytesIO(normalize(data))) as image:
        assert image.convert("RGBA").getpixel((20, 20)) == (0, 0, 0, 255)


@linux_worker
@pytest.mark.parametrize("style", [
    "fill:url(https://example.com/a)", "fill:url(#a)", "fill:var(--a)",
    "fill:blue!important", "fill:blue;fill:red", "fill:blue/*x*/", "@import:x",
    r"fill:\62lue", "fill-opacity:2", "stroke-width:-1", "fill-rule:unknown",
])
def test_static_style_rejects_css_and_invalid_values(style):
    with pytest.raises(ValueError, match="unsupported SVG style"):
        normalize(svg(f'<rect style="{style}"/>'))
