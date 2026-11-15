"""The pipeline version is part of every cache key and every manifest: it has one value."""

from __future__ import annotations

import tomllib
from pathlib import Path

import tombaugh

API_ROOT = Path(__file__).resolve().parents[1]


def test_package_metadata_and_pipeline_version_are_the_same_number() -> None:
    project = tomllib.loads((API_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == tombaugh.__version__


def test_lockfile_records_the_same_version() -> None:
    lock = tomllib.loads((API_ROOT / "uv.lock").read_text(encoding="utf-8"))
    own = [package for package in lock["package"] if package["name"] == "tombaugh"]
    assert len(own) == 1
    assert own[0]["version"] == tombaugh.__version__
