from __future__ import annotations

import stat
import subprocess
import sys
import tarfile
from pathlib import Path


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
    assert archive.name.endswith(".tar.gz")

    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir()
    with tarfile.open(archive, "r:gz") as handle:
        names = handle.getnames()
        roots = {name.split("/", 1)[0] for name in names}
        assert len(roots) == 1
        bundle_root = roots.pop()

        assert f"{bundle_root}/app/Home.py" in names
        assert f"{bundle_root}/run_app.command" in names
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
