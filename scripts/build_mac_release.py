"""Build a deterministic macOS release-candidate source bundle."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_FILE = ROOT / "pyproject.toml"
PACKAGE_INIT = ROOT / "src" / "soil_mir" / "__init__.py"
REQUIRED_FILES = (
    ROOT / "app" / "Home.py",
    ROOT / "pyproject.toml",
    ROOT / "run_app.command",
    ROOT / "src" / "soil_mir" / "__init__.py",
)
INCLUDE_ENTRIES = (
    ROOT / "app",
    ROOT / "src",
    ROOT / "pyproject.toml",
    ROOT / "run_app.command",
    ROOT / "README.md",
    ROOT / "RELEASE_CHECKLIST.md",
)
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def project_version() -> str:
    with PROJECT_FILE.open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def package_version() -> str:
    text = PACKAGE_INIT.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not read __version__ from src/soil_mir/__init__.py")
    return match.group(1)


def validate_release_inputs() -> str:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.exists()]
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


def iter_release_files() -> list[Path]:
    files: list[Path] = []
    for entry in INCLUDE_ENTRIES:
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


def zip_info(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (mode & 0xFFFF) << 16
    return info


def safe_label(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if not label:
        raise ValueError("Release label cannot be empty")
    return label


def build_bundle(output_dir: Path, label: str, commit: str) -> Path:
    version = validate_release_inputs()
    label = safe_label(label)
    commit = safe_label(commit) if commit else "unknown"
    bundle_root = f"soil-mir-app-v{version}-{label}"
    archive = output_dir / f"{bundle_root}-mac.zip"
    output_dir.mkdir(parents=True, exist_ok=True)

    release_readme = f"""Soil MIR PLSR v{version} - macOS release candidate

This release candidate is the local-first Python distribution, not a signed standalone .app.

Requirements
------------
- macOS
- Python 3.10 or newer
- Internet access on first launch so Python dependencies can be installed

Start
-----
1. Extract this ZIP to a normal writable folder.
2. Double-click run_app.command.
3. Keep the Terminal window open while using Soil MIR.
4. The first launch creates a private .venv beside the app and installs dependencies.
5. Later launches reuse that environment unless pyproject.toml changes.

Build
-----
Label: {label}
Commit: {commit}

For release validation, see RELEASE_CHECKLIST.md.
"""

    build_info = f"version={version}\nlabel={label}\ncommit={commit}\n"

    with zipfile.ZipFile(archive, "w") as handle:
        for path in iter_release_files():
            relative = path.relative_to(ROOT).as_posix()
            mode = 0o755 if relative == "run_app.command" else 0o644
            info = zip_info(f"{bundle_root}/{relative}", mode)
            handle.writestr(info, path.read_bytes())

        handle.writestr(
            zip_info(f"{bundle_root}/MAC_RELEASE_README.txt", 0o644),
            release_readme.encode("utf-8"),
        )
        handle.writestr(
            zip_info(f"{bundle_root}/BUILD_INFO.txt", 0o644),
            build_info.encode("utf-8"),
        )

    verify_bundle(archive, bundle_root)
    return archive


def verify_bundle(archive: Path, bundle_root: str) -> None:
    with zipfile.ZipFile(archive) as handle:
        names = set(handle.namelist())
        required = {
            f"{bundle_root}/app/Home.py",
            f"{bundle_root}/pyproject.toml",
            f"{bundle_root}/run_app.command",
            f"{bundle_root}/src/soil_mir/__init__.py",
            f"{bundle_root}/MAC_RELEASE_README.txt",
            f"{bundle_root}/BUILD_INFO.txt",
        }
        missing = sorted(required - names)
        if missing:
            raise RuntimeError(f"Release bundle is missing: {', '.join(missing)}")

        forbidden_prefixes = (
            f"{bundle_root}/tests/",
            f"{bundle_root}/.git/",
            f"{bundle_root}/.venv/",
        )
        if any(name.startswith(forbidden_prefixes) for name in names):
            raise RuntimeError("Release bundle contains development-only content")

        if f"{bundle_root}/.gitlab-ci.yml" in names:
            raise RuntimeError("Release bundle contains .gitlab-ci.yml")

        launcher = handle.getinfo(f"{bundle_root}/run_app.command")
        launcher_mode = (launcher.external_attr >> 16) & 0o777
        if launcher_mode != 0o755:
            raise RuntimeError(
                f"run_app.command must be executable in the ZIP; found mode {oct(launcher_mode)}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("--label", default="rc")
    parser.add_argument("--commit", default="local")
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = validate_release_inputs()
    if args.check_only:
        print(f"Release inputs are valid for v{version}.")
        return 0

    archive = build_bundle(ROOT / args.output_dir, args.label, args.commit)
    print(archive.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
