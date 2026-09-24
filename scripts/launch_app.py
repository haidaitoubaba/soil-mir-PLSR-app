"""Shared cross-platform launcher for Soil MIR."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


MIN_PYTHON = (3, 10)
ROOT = Path(__file__).resolve().parents[1]
STAMP_NAME = ".soil_mir_dependencies"


def version_is_supported(version) -> bool:
    return tuple(version[:2]) >= MIN_PYTHON


def version_text(version) -> str:
    return ".".join(str(part) for part in version[:3])


def venv_python_path(root: Path, platform_name: str | None = None) -> Path:
    platform_name = platform_name or sys.platform
    if platform_name == "win32":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def dependencies_need_install(root: Path) -> bool:
    stamp = root / ".venv" / STAMP_NAME
    pyproject = root / "pyproject.toml"
    if not stamp.exists():
        return True
    return pyproject.stat().st_mtime_ns > stamp.stat().st_mtime_ns


def environment_is_supported(python_executable: Path) -> bool:
    if not python_executable.exists():
        return False
    completed = subprocess.run(
        [
            str(python_executable),
            "-c",
            "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def run_checked(command: list[str], root: Path) -> None:
    subprocess.run(command, cwd=root, check=True)


def ensure_environment(root: Path) -> Path:
    venv_dir = root / ".venv"
    venv_python = venv_python_path(root)

    if venv_python.exists() and not environment_is_supported(venv_python):
        print("[2/4] Existing virtual environment uses an unsupported Python version;")
        print("      rebuilding it...")
        shutil.rmtree(venv_dir)

    if not venv_python.exists():
        print("[2/4] Creating local Python environment...")
        run_checked([sys.executable, "-m", "venv", str(venv_dir)], root)
    else:
        print("[2/4] Local Python environment: ready")

    if not venv_python.exists():
        raise RuntimeError(f"Virtual environment Python was not created at {venv_python}")

    return venv_python


def ensure_dependencies(root: Path, venv_python: Path) -> None:
    if dependencies_need_install(root):
        print("[3/4] Installing or updating Soil MIR dependencies...")
        print("      First setup can take several minutes. Please keep this window open.")
        run_checked([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], root)
        run_checked([str(venv_python), "-m", "pip", "install", "-e", ".[science]"], root)
        (root / ".venv" / STAMP_NAME).touch()
        print("[3/4] Dependencies: ready")
    else:
        print("[3/4] Dependencies: already up to date")


def start_streamlit(root: Path, venv_python: Path) -> int:
    print("[4/4] Starting Soil MIR...")
    print("      Keep this terminal window open while using the app.")
    print("      Your browser should open automatically.")
    print()
    completed = subprocess.run(
        [
            str(venv_python),
            "-m",
            "streamlit",
            "run",
            str(root / "app" / "Home.py"),
        ],
        cwd=root,
        check=False,
    )
    return int(completed.returncode)


def main() -> int:
    print()
    print("Soil MIR PLSR")
    print(f"Project: {ROOT}")
    print()

    if not version_is_supported(sys.version_info):
        print(
            f"Python {version_text(sys.version_info)} was found, "
            "but Soil MIR requires Python 3.10 or newer."
        )
        return 1

    print(f"[1/4] Python {version_text(sys.version_info)}: OK")

    try:
        venv_python = ensure_environment(ROOT)
        ensure_dependencies(ROOT, venv_python)
        return start_streamlit(ROOT, venv_python)
    except KeyboardInterrupt:
        print("\nSoil MIR stopped.")
        return 0
    except subprocess.CalledProcessError as exc:
        print("\nSoil MIR could not start.")
        print(f"A setup command failed with exit code {exc.returncode}.")
        print("You can copy this terminal output when reporting the problem.")
        return int(exc.returncode or 1)
    except (OSError, RuntimeError) as exc:
        print("\nSoil MIR could not start.")
        print(str(exc))
        print("You can copy this terminal output when reporting the problem.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
