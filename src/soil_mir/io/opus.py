from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np


OPUS_NATIVE = "native_npt"
OPUS_LEGACY = "legacy_array_length"


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


def crop_spectrum(
    values: np.ndarray,
    axis: np.ndarray,
    lower: float | None = None,
    upper: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Crop on the native grid and project off-grid boundaries from retained points."""
    axis = validate_wavenumbers(axis)
    values = np.asarray(values, dtype=float)
    if values.shape != axis.shape or not np.isfinite(values).all():
        raise ValueError("Spectrum values must be finite and match their wavenumber axis.")
    if any(bound is not None and not np.isfinite(bound) for bound in (lower, upper)):
        raise ValueError("Crop bounds must be finite.")
    if lower is not None and upper is not None and lower >= upper:
        raise ValueError("The crop minimum must be below the maximum.")
    descending = axis[0] > axis[-1]
    if descending:
        values, axis = values[::-1], axis[::-1]
    low = axis[0] if lower is None else max(axis[0], lower)
    high = axis[-1] if upper is None else min(axis[-1], upper)
    keep = (axis >= low) & (axis <= high)
    x, y = axis[keep], values[keep]
    if len(x) < 2:
        raise ValueError("The requested crop must retain at least two measured points.")
    left_value = y[0] + (low - x[0]) * (y[1] - y[0]) / (x[1] - x[0])
    right_value = y[-1] + (high - x[-1]) * (y[-1] - y[-2]) / (x[-1] - x[-2])
    if low < x[0]:
        x, y = np.insert(x, 0, low), np.insert(y, 0, left_value)
    if high > x[-1]:
        x, y = np.append(x, high), np.append(y, right_value)
    return (y[::-1], x[::-1]) if descending else (y, x)


def read_opus_spectrum(
    path: str | Path, *, opus_axis_mode: str = OPUS_NATIVE
) -> tuple[np.ndarray, np.ndarray]:
    if opus_axis_mode not in (OPUS_NATIVE, OPUS_LEGACY):
        raise ValueError(f"Unknown OPUS axis mode: {opus_axis_mode}")
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

    status_keys = (
        "AB Data Parameter", "AB_Data_Parameter", "Sc Data Parameter", "IgSm Data Parameter"
    )
    if opus_axis_mode == OPUS_NATIVE:
        status_keys = (f"{key} Data Parameter", f"{key}_Data_Parameter", *status_keys)
    params = next((data[name] for name in status_keys if name in data), None)
    if params is None:
        raise ValueError(f"Wavenumber metadata missing in {path}")
    if opus_axis_mode == OPUS_NATIVE:
        declared_count = float(params.get("NPT", len(absorbance)))
        if not declared_count.is_integer() or not 2 <= declared_count <= len(absorbance):
            raise ValueError(f"Invalid OPUS point count {declared_count:g} in {path}")
        absorbance = absorbance[:int(declared_count)] * float(params.get("CSF", 1.0))
    axis = np.linspace(float(params["FXV"]), float(params["LXV"]), len(absorbance))
    if not np.isfinite(absorbance).all() or not np.isfinite(axis).all():
        raise ValueError(f"Non-finite spectral data in {path}")
    return absorbance, validate_wavenumbers(axis)
