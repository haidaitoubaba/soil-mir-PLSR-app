from __future__ import annotations

from collections import Counter
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


def validate_wavenumbers(axis: np.ndarray) -> np.ndarray:
    axis = np.asarray(axis, dtype=float)
    if axis.ndim != 1 or len(axis) < 2 or not np.isfinite(axis).all():
        raise ValueError("Wavenumbers must contain at least two finite coordinates.")
    differences = np.diff(axis)
    if not (np.all(differences > 0) or np.all(differences < 0)):
        raise ValueError("Wavenumbers must be strictly ascending or descending.")
    return axis


def resample_spectrum(
    values: np.ndarray, source_axis: np.ndarray, target_axis: np.ndarray
) -> np.ndarray:
    source_axis = validate_wavenumbers(source_axis)
    target_axis = validate_wavenumbers(target_axis)
    values = np.asarray(values, dtype=float)
    if values.shape != source_axis.shape or not np.isfinite(values).all():
        raise ValueError("Spectrum values must be finite and match their wavenumber axis.")
    if target_axis.min() < source_axis.min() or target_axis.max() > source_axis.max():
        raise ValueError(
            "Spectrum does not cover the target wavenumber grid; extrapolation is disabled."
        )
    if np.array_equal(source_axis, target_axis):
        return values
    if source_axis[0] > source_axis[-1]:
        source_axis, values = source_axis[::-1], values[::-1]
    return np.interp(target_axis, source_axis, values)


def align_spectral_library(
    raw_spectra: dict[str, np.ndarray],
    raw_axes: dict[str, np.ndarray],
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Align spectra on the modal grid inside coverage shared by every spectrum.

    This matches the legacy scientific script: endpoints are trimmed when needed,
    replicate rows are preserved, and extrapolation is never allowed.
    """
    if not raw_spectra or set(raw_spectra) != set(raw_axes):
        raise ValueError(
            "Spectral values and wavenumber axes must contain the same nonempty files."
        )

    axes = {
        name: validate_wavenumbers(axis)
        for name, axis in raw_axes.items()
    }
    modal_length = Counter(
        map(len, axes.values())
    ).most_common(1)[0][0]
    reference_axis = next(
        axis
        for axis in axes.values()
        if len(axis) == modal_length
    )

    lower = max(
        float(np.min(axis))
        for axis in axes.values()
    )
    upper = min(
        float(np.max(axis))
        for axis in axes.values()
    )
    common_axis = np.asarray(
        reference_axis,
        dtype=float,
    )[
        (reference_axis >= lower)
        & (reference_axis <= upper)
    ]

    if len(common_axis) < 2:
        raise ValueError(
            "Spectra have insufficient shared wavenumber coverage."
        )

    aligned = {}
    for name, values in raw_spectra.items():
        try:
            aligned[name] = resample_spectrum(
                values,
                axes[name],
                common_axis,
            )
        except ValueError as exc:
            raise ValueError(
                f"Invalid spectral grid for {name}: {exc}"
            ) from exc

    return aligned, common_axis


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
    return absorbance, validate_wavenumbers(axis)
