from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from soil_mir.io.cache import load_opus_spectra_cached
from soil_mir.io.opus import (
    align_spectral_library,
    list_opus_files,
)
from soil_mir.metrics import (
    grouped_average_frame,
    regression_metrics,
)
from soil_mir.preprocessing import transform_preprocessor
from soil_mir.transforms import back_transform


REQUIRED_MODEL_KEYS = {
    "preprocessing_state",
    "pls_model",
    "wavenumbers",
    "response_transform",
    "response_transform_parameter",
}


def _validate_bundle(bundle: dict) -> None:
    if not isinstance(bundle, dict):
        raise ValueError(
            "The selected file is not a Soil MIR model bundle."
        )
    missing = sorted(REQUIRED_MODEL_KEYS.difference(bundle))
    if missing:
        raise ValueError(
            "Model bundle is missing required keys: "
            f"{missing}"
        )
    if bundle["pls_model"] is None:
        raise ValueError(
            "Model bundle does not contain a fitted PLS model."
        )


def load_model_bundle(model_path: str | Path) -> dict:
    path = Path(model_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(
            f"Model file not found: {path}"
        )
    bundle = joblib.load(path)
    _validate_bundle(bundle)
    return bundle


def resample_spectra_to_model_grid(
    spectra,
    raw_wavenumbers,
    model_wavenumbers,
    max_extrapolation_cm1: float = 0.25,
) -> np.ndarray:
    """Match the external-prediction script's model-grid resampling.

    Tiny endpoint differences can be linearly extrapolated up to the configured
    tolerance. Larger missing ranges are rejected.
    """
    spectra = np.asarray(spectra, dtype=float)
    raw_wavenumbers = np.asarray(
        raw_wavenumbers,
        dtype=float,
    )
    model_wavenumbers = np.asarray(
        model_wavenumbers,
        dtype=float,
    )
    max_extrapolation_cm1 = float(
        max_extrapolation_cm1
    )

    if spectra.ndim != 2:
        raise ValueError(
            "Spectra must be a two-dimensional array."
        )
    if (
        raw_wavenumbers.ndim != 1
        or model_wavenumbers.ndim != 1
    ):
        raise ValueError(
            "Wavenumber arrays must be one-dimensional."
        )
    if (
        len(raw_wavenumbers) == 0
        or len(model_wavenumbers) == 0
    ):
        raise ValueError(
            "Wavenumber arrays must not be empty."
        )
    if spectra.shape[1] != len(raw_wavenumbers):
        raise ValueError(
            "Spectrum length does not match the raw wavenumber grid."
        )
    if (
        not np.isfinite(spectra).all()
        or not np.isfinite(raw_wavenumbers).all()
        or not np.isfinite(model_wavenumbers).all()
    ):
        raise ValueError(
            "Spectra and wavenumber arrays must be finite."
        )
    if (
        not np.isfinite(max_extrapolation_cm1)
        or max_extrapolation_cm1 < 0
    ):
        raise ValueError(
            "max_extrapolation_cm1 must be finite and non-negative."
        )

    raw_diff = np.diff(raw_wavenumbers)
    model_diff = np.diff(model_wavenumbers)
    raw_descending = np.all(raw_diff < 0)
    model_descending = np.all(model_diff < 0)
    raw_ascending = np.all(raw_diff > 0)
    model_ascending = np.all(model_diff > 0)
    if not (raw_descending or raw_ascending):
        raise ValueError(
            "Raw wavenumbers must be strictly monotonic."
        )
    if not (model_descending or model_ascending):
        raise ValueError(
            "Model wavenumbers must be strictly monotonic."
        )

    if raw_descending:
        raw_grid = raw_wavenumbers[::-1]
        spectra_ascending = spectra[:, ::-1]
    else:
        raw_grid = raw_wavenumbers
        spectra_ascending = spectra

    target_grid = (
        model_wavenumbers[::-1]
        if model_descending
        else model_wavenumbers
    )
    lower_gap = max(
        0.0,
        float(raw_grid[0] - target_grid[0]),
    )
    upper_gap = max(
        0.0,
        float(target_grid[-1] - raw_grid[-1]),
    )
    if max(lower_gap, upper_gap) > max_extrapolation_cm1:
        raise ValueError(
            "External spectra do not cover the model wavenumber range: "
            f"lower gap={lower_gap:.6g}, "
            f"upper gap={upper_gap:.6g} cm⁻¹."
        )

    resampled = np.vstack(
        [
            np.interp(
                target_grid,
                raw_grid,
                spectrum,
            )
            for spectrum in spectra_ascending
        ]
    )

    if lower_gap > 0:
        slope = (
            spectra_ascending[:, 1]
            - spectra_ascending[:, 0]
        ) / (raw_grid[1] - raw_grid[0])
        mask = target_grid < raw_grid[0]
        resampled[:, mask] = (
            spectra_ascending[:, [0]]
            + slope[:, None]
            * (
                target_grid[mask]
                - raw_grid[0]
            )
        )

    if upper_gap > 0:
        slope = (
            spectra_ascending[:, -1]
            - spectra_ascending[:, -2]
        ) / (
            raw_grid[-1]
            - raw_grid[-2]
        )
        mask = target_grid > raw_grid[-1]
        resampled[:, mask] = (
            spectra_ascending[:, [-1]]
            + slope[:, None]
            * (
                target_grid[mask]
                - raw_grid[-1]
            )
        )

    return (
        resampled[:, ::-1]
        if model_descending
        else resampled
    )


def load_external_opus_library(
    spectra_dir: str | Path,
    *,
    cache_root: str | Path | None = None,
) -> tuple[
    dict[str, np.ndarray],
    np.ndarray,
    object,
]:
    """Load every OPUS file and align the external library on shared coverage."""
    files = list_opus_files(spectra_dir)
    if not files:
        raise ValueError(
            "No numeric-extension OPUS files were found."
        )

    filenames = [path.name for path in files]
    raw, cache_stats = load_opus_spectra_cached(
        spectra_dir,
        filenames,
        cache_root=cache_root,
    )
    raw_spectra = {
        name: values
        for name, (values, _axis) in raw.items()
    }
    raw_axes = {
        name: axis
        for name, (_values, axis) in raw.items()
    }
    aligned, axis = align_spectral_library(
        raw_spectra,
        raw_axes,
    )
    return aligned, axis, cache_stats


def predict_external_dataset(
    bundle: dict,
    spectra: dict[str, np.ndarray],
    raw_wavenumbers: np.ndarray,
    reference: pd.DataFrame | None = None,
    *,
    file_name_col: str = "File Name",
    sample_col: str = "Sample",
    reference_value_col: str = "Reference Value",
    max_extrapolation_cm1: float = 0.25,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Predict external spectra and optionally calculate validation metrics.

    With a reference table, file order and replicate grouping come from the
    reference worksheet. Without a reference, every OPUS file is its own sample,
    matching the authoritative external-prediction script.
    """
    _validate_bundle(bundle)
    spectra_lookup = {
        Path(path).name: np.asarray(
            spectrum,
            dtype=float,
        )
        for path, spectrum in spectra.items()
    }
    if not spectra_lookup:
        raise ValueError(
            "No external spectra were loaded."
        )

    measured = None
    if reference is not None:
        required_columns = {
            file_name_col,
            sample_col,
        }
        missing_columns = sorted(
            required_columns.difference(
                reference.columns
            )
        )
        if missing_columns:
            raise KeyError(
                "Reference table is missing required columns: "
                f"{', '.join(missing_columns)}"
            )
        file_names = (
            reference[file_name_col]
            .astype(str)
            .str.strip()
            .tolist()
        )
        sample_ids = (
            reference[sample_col]
            .astype(str)
            .str.strip()
            .to_numpy()
        )
        if reference_value_col in reference.columns:
            measured = (
                reference[reference_value_col]
                .astype(float)
                .to_numpy()
            )
    else:
        file_names = sorted(spectra_lookup)
        sample_ids = np.asarray(
            file_names,
            dtype=str,
        )

    missing = [
        name
        for name in file_names
        if name not in spectra_lookup
    ]
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} external spectra were not found. "
            f"First missing file: {missing[0]}"
        )

    X_external_raw = np.vstack(
        [
            spectra_lookup[name]
            for name in file_names
        ]
    )
    X_external = resample_spectra_to_model_grid(
        X_external_raw,
        raw_wavenumbers,
        bundle["wavenumbers"],
        max_extrapolation_cm1=(
            max_extrapolation_cm1
        ),
    )
    X_preprocessed = transform_preprocessor(
        bundle["preprocessing_state"],
        X_external,
    )
    predicted_transformed = (
        bundle["pls_model"]
        .predict(X_preprocessed)
        .ravel()
    )
    predicted = back_transform(
        predicted_transformed,
        bundle["response_transform"],
        bundle["response_transform_parameter"],
    )
    if not np.isfinite(predicted).all():
        raise ValueError(
            "External predictions are non-finite after inverse transformation."
        )

    replicate = pd.DataFrame(
        {
            "Sample": sample_ids,
            "File Name": file_names,
            "Predicted": predicted,
        }
    )
    if measured is not None:
        replicate.insert(
            2,
            "Measured",
            measured,
        )
        replicate["Residual"] = (
            replicate["Measured"]
            - replicate["Predicted"]
        )

    if measured is not None:
        sample = grouped_average_frame(
            measured,
            predicted,
            sample_ids,
        ).rename(
            columns={"Sample Key": "Sample"}
        )
        metrics = regression_metrics(
            sample["Measured"],
            sample["Predicted"],
        )
    else:
        sample = (
            replicate
            .groupby(
                "Sample",
                as_index=False,
            )["Predicted"]
            .mean()
        )
        metrics = {}

    metrics["Samples"] = int(len(sample))
    metrics["Spectra"] = int(len(replicate))
    return replicate, sample, metrics


def predict_opus_directory(
    model_path: str | Path,
    spectra_dir: str | Path,
    *,
    reference: pd.DataFrame | None = None,
    max_extrapolation_cm1: float = 0.25,
    cache_root: str | Path | None = None,
) -> dict:
    bundle = load_model_bundle(model_path)
    spectra, raw_wavenumbers, cache_stats = (
        load_external_opus_library(
            spectra_dir,
            cache_root=cache_root,
        )
    )
    replicate, sample, metrics = (
        predict_external_dataset(
            bundle,
            spectra,
            raw_wavenumbers,
            reference,
            max_extrapolation_cm1=(
                max_extrapolation_cm1
            ),
        )
    )
    return {
        "bundle": bundle,
        "file_predictions": replicate,
        "sample_predictions": sample,
        "metrics": metrics,
        "cache_stats": cache_stats,
        "raw_wavenumbers": raw_wavenumbers,
    }
