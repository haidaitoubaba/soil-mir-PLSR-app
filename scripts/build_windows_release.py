"""Build a deterministic Windows Soil MIR release bundle."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

from release_common import (
    ROOT,
    iter_release_files,
    release_identity,
    validate_release_inputs,
)


WINDOWS_REQUIRED_FILES = (
    ROOT / "run_app.bat",
    ROOT / "run_app.ps1",
    ROOT / "WINDOWS_RELEASE_CHECKLIST.md",
)
WINDOWS_INCLUDE_ENTRIES = WINDOWS_REQUIRED_FILES


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 0
    return info


def add_bytes(handle: zipfile.ZipFile, name: str, content: bytes) -> None:
    handle.writestr(zip_info(name), content)


def windows_file_bytes(path: Path) -> bytes:
    content = path.read_bytes()
    if path.suffix.lower() not in {".bat", ".ps1"}:
        return content

    text = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "\r\n").encode("utf-8")


def build_bundle(output_dir: Path, label: str, commit: str) -> Path:
    version = validate_release_inputs(WINDOWS_REQUIRED_FILES)
    label, bundle_root, is_final_release = release_identity(version, label)
    commit = commit.strip() or "unknown"
    archive = output_dir / f"{bundle_root}-windows.zip"
    output_dir.mkdir(parents=True, exist_ok=True)

    release_kind = "release" if is_final_release else "release candidate"
    release_readme = f"""Soil MIR PLSR v{version} - Windows {release_kind}

This {release_kind} is the local-first Python distribution, not a standalone installer.

Requirements
------------
- 64-bit Windows 10 or Windows 11
- Python 3.10 or newer
- Internet access on first launch so Python dependencies can be installed

Start
-----
1. Extract the ZIP archive to a normal writable folder.
2. Double-click run_app.bat. This is the recommended Windows launcher.
3. Keep the command window open while using Soil MIR.
4. The first launch creates a private .venv beside the app and installs dependencies.
5. Later launches reuse that environment unless pyproject.toml changes.

run_app.ps1 is included as an optional PowerShell launcher. If PowerShell execution
policy blocks it, use run_app.bat instead.

Build
-----
Label: {label}
Commit: {commit}

For release validation, see WINDOWS_RELEASE_CHECKLIST.md.
"""

    build_info = f"version={version}\nlabel={label}\ncommit={commit}\n"

    with zipfile.ZipFile(archive, "w") as handle:
        for path in iter_release_files(WINDOWS_INCLUDE_ENTRIES):
            relative = path.relative_to(ROOT).as_posix()
            add_bytes(
                handle,
                f"{bundle_root}/{relative}",
                windows_file_bytes(path),
            )

        add_bytes(
            handle,
            f"{bundle_root}/WINDOWS_RELEASE_README.txt",
            release_readme.encode("utf-8"),
        )
        add_bytes(
            handle,
            f"{bundle_root}/BUILD_INFO.txt",
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
            f"{bundle_root}/run_app.bat",
            f"{bundle_root}/run_app.ps1",
            f"{bundle_root}/scripts/launch_app.py",
            f"{bundle_root}/src/soil_mir/__init__.py",
            f"{bundle_root}/WINDOWS_RELEASE_README.txt",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("--label", default="rc")
    parser.add_argument("--commit", default="local")
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = validate_release_inputs(WINDOWS_REQUIRED_FILES)
    if args.check_only:
        print(f"Windows release inputs are valid for v{version}.")
        return 0

    archive = build_bundle(ROOT / args.output_dir, args.label, args.commit)
    print(archive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
