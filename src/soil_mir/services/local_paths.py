from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalDataLayout:
    data_dir: Path
    spectra_dir: Path
    reference_excel: Path
    output_dir: Path
    source: str


def _layout_from_data_dir(
    data_dir: Path,
    *,
    source: str,
) -> LocalDataLayout | None:
    data_dir = data_dir.expanduser()
    spectra_dir = data_dir / "spectra" / "Complete"
    reference_excel = (
        data_dir
        / "reference"
        / "reference_value_ZL_trt.xlsx"
    )
    if not spectra_dir.is_dir() or not reference_excel.is_file():
        return None

    return LocalDataLayout(
        data_dir=data_dir,
        spectra_dir=spectra_dir,
        reference_excel=reference_excel,
        output_dir=data_dir / "soil_mir_results",
        source=source,
    )


def detect_local_data_layout(
    *,
    home: str | Path | None = None,
    cwd: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> LocalDataLayout | None:
    environment = os.environ if environ is None else environ
    candidates: list[tuple[str, Path]] = []

    configured = environment.get(
        "SOIL_MIR_DATA_DIR",
        "",
    ).strip()
    if configured:
        candidates.append(
            (
                "SOIL_MIR_DATA_DIR",
                Path(configured),
            )
        )

    working = Path.cwd() if cwd is None else Path(cwd)
    candidates.append(
        ("project data directory", working / "data")
    )

    home_path = Path.home() if home is None else Path(home)
    candidates.append(
        (
            "legacy Downloads directory",
            home_path
            / "Downloads"
            / "Python Code for Zheya"
            / "Python code for MIR"
            / "data",
        )
    )

    seen = set()
    for source, candidate in candidates:
        resolved = candidate.expanduser()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)

        layout = _layout_from_data_dir(
            resolved,
            source=source,
        )
        if layout is not None:
            return layout

    return None


def path_preferences_file(
    *,
    home: str | Path | None = None,
) -> Path:
    home_path = Path.home() if home is None else Path(home)
    return home_path / ".soil_mir_app" / "paths.json"


def load_path_preferences(
    *,
    home: str | Path | None = None,
) -> dict[str, str]:
    path = path_preferences_file(home=home)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    allowed = (
        "spectra_dir",
        "reference_excel",
        "output_dir",
    )
    return {
        key: str(payload[key])
        for key in allowed
        if isinstance(payload.get(key), str)
        and payload[key].strip()
    }


def save_path_preferences(
    spectra_dir: str | Path,
    reference_excel: str | Path,
    output_dir: str | Path,
    *,
    home: str | Path | None = None,
) -> Path:
    path = path_preferences_file(home=home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "spectra_dir": str(Path(spectra_dir).expanduser()),
        "reference_excel": str(
            Path(reference_excel).expanduser()
        ),
        "output_dir": str(Path(output_dir).expanduser()),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _applescript_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def choose_local_path(
    kind: str,
    *,
    prompt: str,
    platform_name: str | None = None,
) -> Path | None:
    """Open a native local file/folder chooser on macOS.

    Manual path entry remains available in the Streamlit UI, so unsupported
    platforms are never required to use this helper.
    """
    platform_value = (
        sys.platform
        if platform_name is None
        else platform_name
    )
    if platform_value != "darwin":
        raise RuntimeError(
            "Native path browsing is currently available on macOS only. "
            "Enter the path manually on this platform."
        )

    safe_prompt = _applescript_string(prompt)
    if kind == "directory":
        chooser = (
            f'choose folder with prompt "{safe_prompt}"'
        )
    elif kind == "file":
        chooser = (
            f'choose file with prompt "{safe_prompt}"'
        )
    else:
        raise ValueError(
            "kind must be 'directory' or 'file'."
        )

    script = f"POSIX path of ({chooser})"
    completed = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        if "User canceled" in completed.stderr:
            return None
        raise RuntimeError(
            "macOS path chooser failed: "
            f"{completed.stderr.strip() or 'unknown error'}"
        )

    selected = completed.stdout.strip()
    return Path(selected) if selected else None
