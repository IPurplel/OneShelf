"""Stored text reading units (format `text`): detected from content, refused unless every section is sanitised."""
import json
import zipfile

import pytest

from oneshelf.integrity.validators import detect_format, validate
from oneshelf.text.container import TEXT_MIMETYPE, open_text_container
from tests.fixtures.builders import make_text_unit, png_bytes


def rewrite(path, replace: dict, *, mimetype=TEXT_MIMETYPE):
    with zipfile.ZipFile(path) as z:
        entries = {n: z.read(n) for n in z.namelist() if n != "mimetype"}
    entries.update(replace)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        for name, data in entries.items():
            if data is not None:
                z.writestr(name, data)
    return path


def test_a_text_unit_round_trips_and_validates(tmp_path):
    path = make_text_unit(tmp_path / "u.ostext", sections=["<p>first</p>", "<p dir='rtl'>مرحبا</p>"],
                          language="ar", direction="rtl")
    result = validate(path)
    assert result.ok and result.format == "text" and result.page_count == 2
    assert result.metadata == {"title": "Chapter 1", "language": "ar"}
    unit = open_text_container(path)
    assert unit.direction == "rtl" and [s.html for s in unit.sections] == ["<p>first</p>", '<p dir="rtl">مرحبا</p>']
    with zipfile.ZipFile(path) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED


def test_a_text_unit_with_images_is_still_text_not_cbz(tmp_path):
    path = rewrite(make_text_unit(tmp_path / "u.ostext"), {"cover.png": png_bytes()})
    assert detect_format(path) == "text"


def test_an_unsanitised_section_is_refused(tmp_path):
    path = rewrite(make_text_unit(tmp_path / "u.ostext"),
                   {"sections/0001.html": b"<p onclick='x()'>t</p><script>alert(1)</script>"})
    result = validate(path)
    assert not result.ok and "not sanitised" in result.reason


@pytest.mark.parametrize(("replace", "reason"), [
    ({"unit.json": None}, "missing unit.json"),
    ({"unit.json": b"{not json"}, "not valid JSON"),
    ({"sections/0001.html": None}, "section missing"),
    ({"sections/0001.html": b"\xff\xfe<p>t</p>"}, "not UTF-8"),
    ({"sections/0001.html": b"<p>   </p>"}, "has no text"),
])
def test_malformed_containers_are_refused(tmp_path, replace, reason):
    result = validate(rewrite(make_text_unit(tmp_path / "u.ostext"), replace))
    assert not result.ok and reason in result.reason


def test_section_paths_outside_sections_are_refused(tmp_path):
    path = make_text_unit(tmp_path / "u.ostext")
    with zipfile.ZipFile(path) as z:
        meta = json.loads(z.read("unit.json"))
    meta["sections"][0]["file"] = "mimetype"
    result = validate(rewrite(path, {"unit.json": json.dumps(meta).encode()}))
    assert not result.ok and "section missing" in result.reason


def test_direction_must_be_known(tmp_path):
    path = make_text_unit(tmp_path / "u.ostext")
    with zipfile.ZipFile(path) as z:
        meta = json.loads(z.read("unit.json"))
    meta["direction"] = "vertical"
    assert not validate(rewrite(path, {"unit.json": json.dumps(meta).encode()})).ok


def test_unsafe_entry_names_are_refused(tmp_path):
    result = validate(rewrite(make_text_unit(tmp_path / "u.ostext"), {"../escape.html": b"<p>x</p>"}))
    assert not result.ok and "unsafe archive entry name" in result.reason
