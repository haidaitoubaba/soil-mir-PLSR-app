from __future__ import annotations

import base64
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


def _choose_macos_path(kind: str, prompt: str) -> Path | None:
    safe_prompt = _applescript_string(prompt)
    if kind == "directory":
        chooser = f'choose folder with prompt "{safe_prompt}"'
    elif kind == "file":
        chooser = f'choose file with prompt "{safe_prompt}"'
    else:
        raise ValueError("kind must be 'directory' or 'file'.")

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


def _windows_picker_script(kind: str) -> str:
    if kind == "directory":
        return """
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $env:SOIL_MIR_PICKER_PROMPT
$dialog.ShowNewFolderButton = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($dialog.SelectedPath)
    [Console]::Write([Convert]::ToBase64String($bytes))
    exit 0
}
exit 2
""".strip()

    if kind == "file":
        return """
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = $env:SOIL_MIR_PICKER_PROMPT
$dialog.Multiselect = $false
$dialog.Filter = "All files (*.*)|*.*"
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($dialog.FileName)
    [Console]::Write([Convert]::ToBase64String($bytes))
    exit 0
}
exit 2
""".strip()

    raise ValueError("kind must be 'directory' or 'file'.")


def _choose_windows_path(kind: str, prompt: str) -> Path | None:
    environment = os.environ.copy()
    environment["SOIL_MIR_PICKER_PROMPT"] = prompt

    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-STA",
                "-Command",
                _windows_picker_script(kind),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
    except OSError as exc:
        raise RuntimeError(
            "Windows path chooser could not start. "
            "Enter the path manually or confirm Windows PowerShell is available."
        ) from exc

    if completed.returncode == 2:
        return None
    if completed.returncode != 0:
        raise RuntimeError(
            "Windows path chooser failed: "
            f"{completed.stderr.strip() or 'unknown error'}"
        )

    encoded = completed.stdout.strip()
    if not encoded:
        return None
    try:
        selected = base64.b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("Windows path chooser returned an invalid path.") from exc
    return Path(selected)


def choose_local_path(
    kind: str,
    *,
    prompt: str,
    platform_name: str | None = None,
) -> Path | None:
    """Open a native local file/folder chooser on supported desktop platforms."""
    platform_value = sys.platform if platform_name is None else platform_name

    if platform_value == "darwin":
        return _choose_macos_path(kind, prompt)
    if platform_value == "win32":
        return _choose_windows_path(kind, prompt)

    raise RuntimeError(
        "Native path browsing is currently available on macOS and Windows. "
        "Enter the path manually on this platform."
    )


def open_local_folder(
    path: str | Path,
    *,
    platform_name: str | None = None,
) -> Path:
    """Open a local directory in Finder or Windows Explorer."""
    folder = Path(path).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError(f"Results folder not found: {folder}")

    platform_value = sys.platform if platform_name is None else platform_name

    if platform_value == "darwin":
        completed = subprocess.run(
            ["open", str(folder)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Could not open the folder in Finder: "
                f"{completed.stderr.strip() or 'unknown error'}"
            )
        return folder

    if platform_value == "win32":
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            raise RuntimeError("Windows Explorer integration is unavailable.")
        try:
            startfile(str(folder))
        except OSError as exc:
            raise RuntimeError(
                f"Could not open the folder in Windows Explorer: {exc}"
            ) from exc
        return folder

    raise RuntimeError(
        "Open results folder is currently available on macOS and Windows. "
        f"Folder: {folder}"
    )
