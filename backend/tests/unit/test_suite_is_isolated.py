"""Master §53: tests never run against a real library. Isolated data only, and the OneShelf Test Source.

The suite creates real databases, writes real files and deletes them again, so the rule that it must
never do any of that outside pytest's tmp_path is worth holding mechanically rather than by habit.
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]

# Ways a test could reach a real person's data instead of its own sandbox.
FORBIDDEN = (
    (re.compile(r"Path\.home\(\)"), "Path.home()"),
    (re.compile(r"expanduser"), "expanduser"),
    (re.compile(r"""["']~/"""), "a ~/ path"),
    (re.compile(r"""["']/home/"""), "an absolute /home path"),
    (re.compile(r"""["']/var/"""), "an absolute /var path"),
    # `/etc/passwd` is deliberately absent here: it appears in this suite only as a hostile *input* that
    # path safety and package validation must reject, which is the opposite of reaching real data.
    (re.compile(r"os\.getcwd\(\)"), "the working directory"),
)


SELF = Path(__file__).resolve()


def _test_sources() -> list[Path]:
    """Every test module but this one, which necessarily spells out the things it forbids."""
    return [path for path in TESTS.rglob("*.py")
            if "__pycache__" not in path.parts and path.resolve() != SELF]


def test_no_test_reaches_outside_its_own_temporary_directory():
    offenders = []
    for path in _test_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for pattern, what in FORBIDDEN:
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(TESTS)}:{number} uses {what}")
    assert offenders == [], offenders


def test_every_data_directory_a_test_configures_is_a_temporary_one():
    """`ONESHELF_DATA_DIR` decides where a whole application instance writes."""
    offenders = []
    for path in _test_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "ONESHELF_DATA_DIR" not in line or line.lstrip().startswith("#"):
                continue
            if "tmp_path" not in line and "tmp" not in line:
                offenders.append(f"{path.relative_to(TESTS)}:{number}")
    assert offenders == [], offenders


def test_the_live_source_suite_is_the_only_test_that_needs_the_real_internet():
    """Everything else runs against the Test Source or fixtures, so a normal run touches no network."""
    marked = {path.relative_to(TESTS).as_posix() for path in _test_sources()
              if "pytest.mark.live" in path.read_text(encoding="utf-8")}
    assert marked == {"live/test_source_suite.py"}, marked
