from __future__ import annotations

import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from soil_mir import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_mac_release_bundle_preserves_launcher_permission_after_extract(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_mac_release.py",
            "--output-dir",
            str(output_dir),
            "--label",
            "test-rc",
            "--commit",
            "deadbeef",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    archive = Path(completed.stdout.strip())
    assert archive.exists()
    assert archive.name == f"soil-mir-app-v{__version__}-test-rc-mac.tar.gz"

    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir()
    with tarfile.open(archive, "r:gz") as handle:
        names = handle.getnames()
        roots = {name.split("/", 1)[0] for name in names}
        assert len(roots) == 1
        bundle_root = roots.pop()

        assert f"{bundle_root}/app/Home.py" in names
        assert f"{bundle_root}/run_app.command" in names
        assert f"{bundle_root}/scripts/launch_app.py" in names
        assert f"{bundle_root}/MAC_RELEASE_README.txt" in names
        assert f"{bundle_root}/BUILD_INFO.txt" in names
        assert not any(name.startswith(f"{bundle_root}/tests/") for name in names)
        assert f"{bundle_root}/.gitlab-ci.yml" not in names

        launcher_member = handle.getmember(f"{bundle_root}/run_app.command")
        assert launcher_member.mode == 0o755
        handle.extractall(extract_dir)

    launcher = extract_dir / bundle_root / "run_app.command"
    assert launcher.exists()
    assert stat.S_IMODE(launcher.stat().st_mode) == 0o755


def test_final_release_tag_uses_clean_artifact_name(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_mac_release.py",
            "--output-dir",
            str(output_dir),
            "--label",
            f"v{__version__}",
            "--commit",
            "cafebabe",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    archive = Path(completed.stdout.strip())
    assert archive.name == f"soil-mir-app-v{__version__}-mac.tar.gz"

    with tarfile.open(archive, "r:gz") as handle:
        roots = {name.split("/", 1)[0] for name in handle.getnames()}
        assert roots == {f"soil-mir-app-v{__version__}"}
        readme = handle.extractfile(
            f"soil-mir-app-v{__version__}/MAC_RELEASE_README.txt"
        )
        assert readme is not None
        text = readme.read().decode("utf-8")
        assert "macOS release\n" in text
        assert "macOS release candidate" not in text



def test_windows_release_bundle_contains_cross_platform_launcher(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_windows_release.py",
            "--output-dir",
            str(output_dir),
            "--label",
            "test-rc",
            "--commit",
            "deadbeef",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    archive = Path(completed.stdout.strip())
    assert archive.exists()
    assert archive.name == f"soil-mir-app-v{__version__}-test-rc-windows.zip"

    with zipfile.ZipFile(archive) as handle:
        names = handle.namelist()
        roots = {name.split("/", 1)[0] for name in names}
        assert len(roots) == 1
        bundle_root = roots.pop()

        assert f"{bundle_root}/app/Home.py" in names
        assert f"{bundle_root}/run_app.bat" in names
        assert f"{bundle_root}/run_app.ps1" in names
        assert f"{bundle_root}/scripts/launch_app.py" in names
        assert f"{bundle_root}/WINDOWS_RELEASE_README.txt" in names
        assert f"{bundle_root}/BUILD_INFO.txt" in names
        assert not any(name.startswith(f"{bundle_root}/tests/") for name in names)
        assert f"{bundle_root}/.gitlab-ci.yml" not in names

        batch = handle.read(f"{bundle_root}/run_app.bat")
        batch.decode("ascii")
        assert b"scripts\\launch_app.py" in batch
        assert b"\r\n" in batch
        assert b"^>=" not in batch


def test_release_builders_share_version_and_bundle_naming_helpers():
    mac_source = (ROOT / "scripts" / "build_mac_release.py").read_text(encoding="utf-8")
    windows_source = (ROOT / "scripts" / "build_windows_release.py").read_text(encoding="utf-8")

    assert "from release_common import" in mac_source
    assert "from release_common import" in windows_source
    assert "release_identity" in mac_source
    assert "release_identity" in windows_source



def test_windows_final_release_tag_uses_clean_artifact_name(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_windows_release.py",
            "--output-dir",
            str(output_dir),
            "--label",
            f"v{__version__}",
            "--commit",
            "cafebabe",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    archive = Path(completed.stdout.strip())
    assert archive.name == f"soil-mir-app-v{__version__}-windows.zip"

    with zipfile.ZipFile(archive) as handle:
        roots = {name.split("/", 1)[0] for name in handle.namelist()}
        assert roots == {f"soil-mir-app-v{__version__}"}
        text = handle.read(
            f"soil-mir-app-v{__version__}/WINDOWS_RELEASE_README.txt"
        ).decode("utf-8")
        assert "Windows release\n" in text
        assert "Windows release candidate" not in text


@pytest.mark.parametrize("prefix", ["v", ""])
@pytest.mark.parametrize("platform", ["mac", "windows"])
def test_versioned_release_candidate_uses_clean_artifact_name(
    tmp_path: Path, prefix: str, platform: str
) -> None:
    label = f"{prefix}{__version__}-rc1"
    expected_root = f"soil-mir-app-v{__version__}-rc1"
    extension = "tar.gz" if platform == "mac" else "zip"
    completed = subprocess.run(
        [
            sys.executable,
            f"scripts/build_{platform}_release.py",
            "--output-dir",
            str(tmp_path / "dist"),
            "--label",
            label,
            "--commit",
            "cafebabe",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    archive = Path(completed.stdout.strip())
    assert archive.name == f"{expected_root}-{platform}.{extension}"
    assert archive.is_file()

    if platform == "mac":
        with tarfile.open(archive, "r:gz") as handle:
            assert {name.split("/", 1)[0] for name in handle.getnames()} == {expected_root}
            launcher = handle.getmember(f"{expected_root}/run_app.command")
            assert launcher.mode == 0o755
            readme = handle.extractfile(f"{expected_root}/MAC_RELEASE_README.txt")
            assert readme is not None
            assert "macOS release candidate" in readme.read().decode("utf-8")
    else:
        with zipfile.ZipFile(archive) as handle:
            assert {name.split("/", 1)[0] for name in handle.namelist()} == {expected_root}
            assert handle.testzip() is None
            assert f"{expected_root}/run_app.bat" in handle.namelist()
            readme = handle.read(f"{expected_root}/WINDOWS_RELEASE_README.txt")
            assert "Windows release candidate" in readme.decode("utf-8")
