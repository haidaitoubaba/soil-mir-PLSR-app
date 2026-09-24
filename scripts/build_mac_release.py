"""Build a deterministic macOS Soil MIR release bundle."""

from __future__ import annotations

import argparse
import gzip
import io
import sys
import tarfile
from pathlib import Path

from release_common import (
    ROOT,
    iter_release_files,
    release_identity,
    validate_release_inputs,
)


MAC_REQUIRED_FILES = (
    ROOT / "run_app.command",
    ROOT / "RELEASE_CHECKLIST.md",
)
MAC_INCLUDE_ENTRIES = MAC_REQUIRED_FILES


def tar_info(name: str, mode: int, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def add_bytes(handle: tarfile.TarFile, name: str, content: bytes, mode: int) -> None:
    handle.addfile(tar_info(name, mode, len(content)), io.BytesIO(content))


def build_bundle(output_dir: Path, label: str, commit: str) -> Path:
    version = validate_release_inputs(MAC_REQUIRED_FILES)
    label, bundle_root, is_final_release = release_identity(version, label)
    commit = commit.strip() or "unknown"
    archive = output_dir / f"{bundle_root}-mac.tar.gz"
    output_dir.mkdir(parents=True, exist_ok=True)

    release_kind = "release" if is_final_release else "release candidate"
    release_readme = f"""Soil MIR PLSR v{version} - macOS {release_kind}

This {release_kind} is the local-first Python distribution, not a signed standalone .app.

Requirements
------------
- macOS
- Python 3.10 or newer
- Internet access on first launch so Python dependencies can be installed

Start
-----
1. Double-click the .tar.gz archive to extract it to a normal writable folder.
2. Open the extracted folder and double-click run_app.command.
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

    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as handle:
                for path in iter_release_files(MAC_INCLUDE_ENTRIES):
                    relative = path.relative_to(ROOT).as_posix()
                    mode = 0o755 if relative == "run_app.command" else 0o644
                    add_bytes(
                        handle,
                        f"{bundle_root}/{relative}",
                        path.read_bytes(),
                        mode,
                    )

                add_bytes(
                    handle,
                    f"{bundle_root}/MAC_RELEASE_README.txt",
                    release_readme.encode("utf-8"),
                    0o644,
                )
                add_bytes(
                    handle,
                    f"{bundle_root}/BUILD_INFO.txt",
                    build_info.encode("utf-8"),
                    0o644,
                )

    verify_bundle(archive, bundle_root)
    return archive


def verify_bundle(archive: Path, bundle_root: str) -> None:
    with tarfile.open(archive, "r:gz") as handle:
        members = {member.name: member for member in handle.getmembers()}
        required = {
            f"{bundle_root}/app/Home.py",
            f"{bundle_root}/pyproject.toml",
            f"{bundle_root}/run_app.command",
            f"{bundle_root}/scripts/launch_app.py",
            f"{bundle_root}/src/soil_mir/__init__.py",
            f"{bundle_root}/MAC_RELEASE_README.txt",
            f"{bundle_root}/BUILD_INFO.txt",
        }
        missing = sorted(required - members.keys())
        if missing:
            raise RuntimeError(f"Release bundle is missing: {', '.join(missing)}")

        forbidden_prefixes = (
            f"{bundle_root}/tests/",
            f"{bundle_root}/.git/",
            f"{bundle_root}/.venv/",
        )
        if any(name.startswith(forbidden_prefixes) for name in members):
            raise RuntimeError("Release bundle contains development-only content")

        if f"{bundle_root}/.gitlab-ci.yml" in members:
            raise RuntimeError("Release bundle contains .gitlab-ci.yml")

        launcher = members[f"{bundle_root}/run_app.command"]
        if launcher.mode != 0o755:
            raise RuntimeError(
                "run_app.command must be executable in the tarball; "
                f"found mode {oct(launcher.mode)}"
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
    version = validate_release_inputs(MAC_REQUIRED_FILES)
    if args.check_only:
        print(f"macOS release inputs are valid for v{version}.")
        return 0

    archive = build_bundle(ROOT / args.output_dir, args.label, args.commit)
    print(archive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
