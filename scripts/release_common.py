"""Shared helpers for deterministic Soil MIR release bundles."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_FILE = ROOT / "pyproject.toml"
PACKAGE_INIT = ROOT / "src" / "soil_mir" / "__init__.py"
CORE_REQUIRED_FILES = (
    ROOT / "app" / "Home.py",
    PROJECT_FILE,
    PACKAGE_INIT,
    ROOT / "scripts" / "launch_app.py",
)
CORE_INCLUDE_ENTRIES = (
    ROOT / "app",
    ROOT / "src",
    PROJECT_FILE,
    ROOT / "README.md",
    ROOT / "scripts" / "launch_app.py",
)


def project_version() -> str:
    with PROJECT_FILE.open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def package_version() -> str:
    text = PACKAGE_INIT.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not read __version__ from src/soil_mir/__init__.py")
    return match.group(1)


def validate_release_inputs(additional_required=()) -> str:
    required = (*CORE_REQUIRED_FILES, *additional_required)
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Missing required release files: {', '.join(missing)}")

    pyproject_version = project_version()
    init_version = package_version()
    if pyproject_version != init_version:
        raise RuntimeError(
            "Release version mismatch: "
            f"pyproject.toml={pyproject_version}, soil_mir.__version__={init_version}"
        )
    return pyproject_version


def iter_release_files(additional_entries=()) -> list[Path]:
    files: list[Path] = []
    entries = (*CORE_INCLUDE_ENTRIES, *additional_entries)
    for entry in entries:
        if entry.is_file():
            files.append(entry)
            continue
        for path in sorted(entry.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            files.append(path)
    return sorted(set(files))


def safe_label(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if not label:
        raise ValueError("Release label cannot be empty")
    return label


def release_identity(version: str, label: str) -> tuple[str, str, bool]:
    clean_label = safe_label(label)
    is_final_release = clean_label in {version, f"v{version}"}
    bundle_root = (
        f"soil-mir-app-v{version}"
        if is_final_release
        else f"soil-mir-app-v{version}-{clean_label}"
    )
    return clean_label, bundle_root, is_final_release
