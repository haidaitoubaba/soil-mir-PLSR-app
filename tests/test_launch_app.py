from __future__ import annotations

import importlib.util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "soil_mir_launcher",
    ROOT / "scripts" / "launch_app.py",
)
assert SPEC is not None
assert SPEC.loader is not None
LAUNCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAUNCHER)


def test_launcher_version_check():
    assert LAUNCHER.version_is_supported((3, 10, 0))
    assert LAUNCHER.version_is_supported((3, 12, 1))
    assert not LAUNCHER.version_is_supported((3, 9, 18))


def test_launcher_uses_platform_specific_virtualenv_python(tmp_path: Path):
    windows = LAUNCHER.venv_python_path(tmp_path, "win32")
    posix = LAUNCHER.venv_python_path(tmp_path, "darwin")

    assert windows == tmp_path / ".venv" / "Scripts" / "python.exe"
    assert posix == tmp_path / ".venv" / "bin" / "python"


def test_dependency_stamp_controls_reinstall(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='test'\n", encoding="utf-8")
    venv = tmp_path / ".venv"
    venv.mkdir()
    stamp = venv / LAUNCHER.STAMP_NAME

    assert LAUNCHER.dependencies_need_install(tmp_path)

    stamp.touch()
    newer = pyproject.stat().st_mtime_ns + 1_000_000_000
    os.utime(stamp, ns=(newer, newer))
    assert not LAUNCHER.dependencies_need_install(tmp_path)

    newest = newer + 1_000_000_000
    os.utime(pyproject, ns=(newest, newest))
    assert LAUNCHER.dependencies_need_install(tmp_path)


def test_platform_wrappers_delegate_to_shared_launcher():
    mac = (ROOT / "run_app.command").read_text(encoding="utf-8")
    batch = (ROOT / "run_app.bat").read_text(encoding="utf-8")
    powershell = (ROOT / "run_app.ps1").read_text(encoding="utf-8")

    assert "scripts/launch_app.py" in mac
    assert "scripts\\launch_app.py" in batch
    assert "scripts\\launch_app.py" in powershell
    assert "pip install" not in mac
    assert "pip install" not in batch
    assert "pip install" not in powershell



def test_windows_batch_version_check_uses_literal_comparison():
    batch = (ROOT / "run_app.bat").read_text(encoding="utf-8")
    assert "sys.version_info >= (3, 10)" in batch
    assert "^>=" not in batch
