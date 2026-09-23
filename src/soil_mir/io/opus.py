from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class OpusDirectorySummary:
    directory: Path
    file_count: int
    extension_counts: dict[str, int]
    total_bytes: int
    filenames: tuple[str, ...]


def list_opus_files(directory: str | Path) -> list[Path]:
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"OPUS directory not found: {directory}")
    files = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix[1:].isdigit()
    ]
    return sorted(files, key=lambda path: path.name)


def inspect_opus_directory(directory: str | Path) -> OpusDirectorySummary:
    directory = Path(directory)
    files = list_opus_files(directory)
    counts: dict[str, int] = {}
    for path in files:
        counts[path.suffix] = counts.get(path.suffix, 0) + 1
    return OpusDirectorySummary(
        directory=directory,
        file_count=len(files),
        extension_counts=dict(sorted(counts.items())),
        total_bytes=sum(path.stat().st_size for path in files),
        filenames=tuple(path.name for path in files),
    )


def read_opus_spectrum(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Read one Bruker OPUS spectrum and return absorbance + wavenumber arrays."""
    try:
        from brukeropusreader import read_file
    except ImportError as exc:
        raise ImportError(
            "brukeropusreader is required to read OPUS files. Install the science extra."
        ) from exc

    data = read_file(str(path))
    absorbance = None
    for key in ("AB", "IgSm", "ScSm", "ScRf", "Sc"):
        if key in data and hasattr(data[key], "__len__"):
            absorbance = np.asarray(data[key], dtype=float)
            break
    if absorbance is None:
        raise ValueError(f"No supported absorbance block found in {path}")

    axis = None
    for key in (
        "AB Data Parameter",
        "AB_Data_Parameter",
        "Sc Data Parameter",
        "IgSm Data Parameter",
    ):
        if key in data:
            params = data[key]
            axis = np.linspace(float(params["FXV"]), float(params["LXV"]), len(absorbance))
            break
    if axis is None:
        raise ValueError(f"Wavenumber metadata missing in {path}")
    if not np.isfinite(absorbance).all() or not np.isfinite(axis).all():
        raise ValueError(f"Non-finite spectral data in {path}")
    return absorbance, axis
