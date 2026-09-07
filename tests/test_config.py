"""Configuration layering.

The one rule worth a test: the environment outranks ``config.yaml``. Every
shipped deployment depends on it — ``deploy/Dockerfile`` and
``deploy/docker-compose.yml`` set
``MD_OUTPUT_DIR``/``MD_CONFIG_DIR``/``MD_PORT`` in the environment while
pointing ``MD_CONFIG_FILE`` at the persisted YAML settings. Get the ordering
wrong and the file wins: the container writes to the path the file names and
quietly ignores the volume it was mounted.

pydantic-settings ranks constructor keyword arguments *highest* by default, and
``load_settings`` passes the YAML that way, so this is exactly the direction the
default gets backwards.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app import config as config_module
from app.config import Settings, load_settings


def _with_yaml(tmp_path: Path, monkeypatch, values: dict) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(values), encoding="utf-8")
    monkeypatch.setattr(config_module, "CONFIG_FILE", path)
    return path


def test_the_environment_wins_over_the_config_file(tmp_path, monkeypatch):
    _with_yaml(tmp_path, monkeypatch, {
        "output_dir": str(tmp_path / "from-yaml"),
        "port": 8080,
        "requests_per_second": 2.0,
    })
    monkeypatch.setenv("MD_OUTPUT_DIR", str(tmp_path / "from-env"))
    monkeypatch.setenv("MD_PORT", "9999")

    settings = load_settings()

    assert settings.output_dir == tmp_path / "from-env"
    assert settings.port == 9999
    # Untouched by the environment, so the file is still the answer.
    assert settings.requests_per_second == 2.0


def test_the_config_file_still_beats_the_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("MD_OUTPUT_DIR", raising=False)
    monkeypatch.delenv("MD_PORT", raising=False)
    _with_yaml(tmp_path, monkeypatch, {
        "output_dir": str(tmp_path / "from-yaml"),
        "port": 8123,
    })

    settings = load_settings()

    assert settings.output_dir == tmp_path / "from-yaml"
    assert settings.port == 8123


def test_a_missing_config_file_is_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_FILE", tmp_path / "absent.yaml")
    monkeypatch.delenv("MD_PORT", raising=False)

    assert load_settings().port == Settings.model_fields["port"].default
