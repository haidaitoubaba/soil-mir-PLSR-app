from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mac_release_bundle_contains_only_distribution_files(tmp_path: Path) -> None:
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

    archive = ROOT / completed.stdout.strip()
    assert archive.exists()

    with zipfile.ZipFile(archive) as handle:
        names = handle.namelist()
        roots = {name.split("/", 1)[0] for name in names}
        assert len(roots) == 1
        bundle_root = roots.pop()

        assert f"{bundle_root}/app/Home.py" in names
        assert f"{bundle_root}/run_app.command" in names
        assert f"{bundle_root}/MAC_RELEASE_README.txt" in names
        assert f"{bundle_root}/BUILD_INFO.txt" in names
        assert not any(name.startswith(f"{bundle_root}/tests/") for name in names)
        assert f"{bundle_root}/.gitlab-ci.yml" not in names

        launcher = handle.getinfo(f"{bundle_root}/run_app.command")
        assert ((launcher.external_attr >> 16) & 0o777) == 0o755
