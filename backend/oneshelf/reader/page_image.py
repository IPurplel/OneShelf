"""Normalize static SVG reader pages in a bounded worker; never serve active SVG.

Only self-contained geometry and validated embedded JPEG/PNG images are accepted.
The worker has no source session and never receives a URL or a filesystem resource base.
"""
from __future__ import annotations

import asyncio
import base64
import io
import math
from pathlib import Path
import re
import sys
import threading

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 8_000_000
MAX_EMBEDDED_PIXELS = 8_000_000
WALL_SECONDS = 8
MEMORY_BYTES = 256 * 1024 * 1024
_slots = threading.BoundedSemaphore(2)
_SVG = "http://www.w3.org/2000/svg"
_XLINK = "http://www.w3.org/1999/xlink"
_XML = "http://www.w3.org/XML/1998/namespace"
_TAGS = {"svg", "g", "defs", "symbol", "path", "clipPath", "image", "use", "rect",
         "circle", "ellipse", "line", "polyline", "polygon", "linearGradient", "radialGradient", "stop"}
_ATTRS = {"id", "version", "width", "height", "viewBox", "preserveAspectRatio", "x", "y", "x1", "y1",
          "x2", "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy", "d", "points", "transform", "fill",
          "fill-rule", "fill-opacity", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
          "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "stroke-opacity", "opacity",
          "clip-path", "clip-rule", "clipPathUnits", "href", "gradientUnits", "gradientTransform",
          "spreadMethod", "offset", "stop-color", "stop-opacity", "overflow"}
_FRAGMENT = re.compile(r"#[A-Za-z_][A-Za-z0-9_.:-]*\Z")
_LOCAL_PAINT = re.compile(r"url\(\s*#[A-Za-z_][A-Za-z0-9_.:-]*\s*\)\Z", re.I)


async def normalize_page_image(data: bytes) -> bytes:
    """Return original raster bytes or PNG bytes from the supported static SVG subset.

    SVG conversion fails closed outside Linux, where the worker's OS limits are unavailable.
    Invalid raster data remains the existing integrity validator's responsibility.
    """
    lead = data.removeprefix(b"\xef\xbb\xbf").lstrip()
    if not lead.startswith((b"<svg", b"<?xml")):
        return data
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("SVG input exceeds byte limit")
    if sys.platform != "linux":
        raise ValueError("SVG rendering requires the bounded Linux worker")
    acquired = False
    process = None
    try:
        async with asyncio.timeout(WALL_SECONDS):
            while not _slots.acquire(blocking=False):
                await asyncio.sleep(0.02)
            acquired = True
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-I", str(Path(__file__).resolve()),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            output, error = await process.communicate(data)
            if process.returncode != 0:
                detail = error.decode("utf-8", errors="replace").strip()[:300]
                raise ValueError(detail or "SVG worker exceeded its resource limit or failed")
            if len(output) > MAX_OUTPUT_BYTES or not output.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("SVG worker returned invalid or oversized output")
            return output
    except TimeoutError as exc:
        raise ValueError("SVG rendering exceeded time limit") from exc
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.communicate()
        if acquired:
            _slots.release()


def _embedded_image(value: str) -> int:
    from PIL import Image
    import warnings

    formats = {"data:image/jpeg;base64,": "JPEG", "data:image/png;base64,": "PNG"}
    prefix = next((p for p in formats if value.startswith(p)), None)
    if prefix is None:
        raise ValueError("unsupported SVG data reference")
    try:
        binary = base64.b64decode(value[len(prefix):], validate=True)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with Image.open(io.BytesIO(binary)) as image:
                pixels = image.width * image.height
                if pixels > MAX_EMBEDDED_PIXELS:
                    raise ValueError("SVG embedded image exceeds pixel limit")
                if image.format != formats[prefix]:
                    raise ValueError("SVG embedded image MIME does not match bytes")
                image.verify()
            with Image.open(io.BytesIO(binary)) as image:
                image.load()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("invalid SVG embedded raster image") from exc
    return pixels


def _dimension(value: str | None) -> float:
    if value is None or not re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)(?:px|pt)?", value):
        raise ValueError("unsupported SVG dimensions")
    result = (float(value[:-2]) * 96 / 72 if value.endswith("pt")
              else float(value.removesuffix("px")))
    if not math.isfinite(result) or result <= 0:
        raise ValueError("invalid SVG dimensions")
    return result


def _presentation_style(node) -> None:
    """Convert a small static declaration subset; never pass CSS to the renderer."""
    style = node.attrib.pop("style", None)
    if style is None:
        return
    if not style.isascii() or any(token in style for token in ("@", "\\", "/*", "*/", "!", "(", ")")):
        raise ValueError("unsupported SVG style")
    properties = {}
    for declaration in style.split(";"):
        if not declaration.strip():
            continue
        if declaration.count(":") != 1:
            raise ValueError("unsupported SVG style")
        key, value = (part.strip() for part in declaration.split(":"))
        valid = False
        if key in {"fill", "stroke"}:
            valid = re.fullmatch(r"(?:[a-zA-Z]+|#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6})", value) is not None
        elif key in {"fill-opacity", "stroke-opacity"}:
            valid = re.fullmatch(r"(?:0|1|0?\.\d+|1\.0*)", value) is not None and 0 <= float(value) <= 1
        elif key == "stroke-width":
            valid = re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)", value) is not None
            valid = valid and math.isfinite(float(value)) and float(value) > 0
        elif key == "fill-rule":
            valid = value in {"nonzero", "evenodd"}
        elif key == "stroke-linecap":
            valid = value in {"butt", "round", "square"}
        elif key == "stroke-linejoin":
            valid = value in {"miter", "round", "bevel"}
        elif key == "stroke-miterlimit":
            valid = re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)", value) is not None
            valid = valid and math.isfinite(float(value)) and float(value) >= 1
        if not valid or key in properties:
            raise ValueError("unsupported SVG style")
        properties[key] = value
    node.attrib.update(properties)


def _render(data: bytes) -> bytes:
    from defusedxml import ElementTree
    from defusedxml.common import DefusedXmlException
    import resvg_py

    try:
        parser = ElementTree.iterparse(io.BytesIO(data), events=("start", "pi"),
                                      forbid_dtd=True, forbid_entities=True, forbid_external=True)
        nodes = []
        for event, node in parser:
            if event == "pi":
                raise ValueError("SVG processing instruction is forbidden")
            nodes.append(node)
            if len(nodes) > 10_000:
                raise ValueError("SVG exceeds element limit")
        root = parser.root
    except DefusedXmlException as exc:
        raise ValueError("SVG DTD and entities are forbidden") from exc
    except ElementTree.ParseError as exc:
        raise ValueError("malformed SVG XML") from exc
    if root.tag != f"{{{_SVG}}}svg":
        raise ValueError("unsupported SVG root")
    width_px, height_px = _dimension(root.get("width")), _dimension(root.get("height"))
    width, height = math.ceil(width_px * 2), math.ceil(height_px * 2)
    root.set("width", f"{width_px}px")
    root.set("height", f"{height_px}px")
    if width > 16_384 or height > 16_384 or width * height > MAX_PIXELS:
        raise ValueError("SVG exceeds output pixel limit")

    embedded_pixels = 0
    for node in nodes:
        tag = node.tag.removeprefix(f"{{{_SVG}}}")
        if node.tag != f"{{{_SVG}}}{tag}" or tag not in _TAGS:
            raise ValueError("unsupported SVG element")
        _presentation_style(node)
        for name, value in node.attrib.items():
            if name == f"{{{_XML}}}base":
                raise ValueError("SVG base URI is forbidden")
            if name.lower().startswith("on"):
                raise ValueError("SVG event handler is forbidden")
            key = "href" if name == f"{{{_XLINK}}}href" else name
            if key not in _ATTRS:
                raise ValueError("unsupported SVG attribute")
            if key == "overflow" and value not in {"visible", "hidden"}:
                raise ValueError("unsupported SVG overflow")
            if key == "href":
                if value.startswith("data:"):
                    if tag != "image":
                        raise ValueError("unsupported SVG data reference")
                    embedded_pixels += _embedded_image(value)
                    if embedded_pixels > MAX_EMBEDDED_PIXELS:
                        raise ValueError("SVG embedded images exceed aggregate pixel limit")
                elif not _FRAGMENT.fullmatch(value):
                    raise ValueError("SVG external reference is forbidden")
            elif "\\" in value or (re.search(r"url\s*\(", value, re.I) and not _LOCAL_PAINT.fullmatch(value)):
                raise ValueError("SVG external reference is forbidden")
    # Serialize only the parsed, checked tree. No source URI, stylesheets, system fonts or file paths.
    result = resvg_py.svg_to_bytes(svg_string=ElementTree.tostring(root, encoding="unicode"),
                                  width=width, height=height, skip_system_fonts=True)
    if len(result) > MAX_OUTPUT_BYTES:
        raise ValueError("SVG output exceeds byte limit")
    return result


def _worker() -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    try:
        data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise ValueError("SVG input exceeds byte limit")
        sys.stdout.buffer.write(_render(data))
    except Exception as exc:
        # Never expose source markup, URL tokens, file paths or raw renderer diagnostics.
        detail = str(exc) if isinstance(exc, ValueError) else "SVG worker could not render the page"
        sys.stderr.write(detail[:300])
        raise SystemExit(1)


if __name__ == "__main__":
    _worker()
