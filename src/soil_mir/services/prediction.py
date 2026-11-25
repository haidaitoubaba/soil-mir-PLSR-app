from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from soil_mir.io.cache import OpusCacheStats, load_opus_spectra_cached
from soil_mir.io.opus import (
    OPUS_LEGACY,
    OPUS_NATIVE,
    align_spectral_library,
    crop_spectrum,
    list_opus_files,
    validate_wavenumbers,
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


def _reference_filenames(
    reference: pd.DataFrame,
    *,
    file_name_col: str = "File Name",
) -> list[str]:
    if file_name_col not in reference.columns:
        raise KeyError(
            f"Reference table is missing required column: {file_name_col}"
        )
    filenames = [
        value
        for value in (
            reference[file_name_col]
            .astype(str)
            .str.strip()
            .tolist()
        )
        if value
    ]
    return list(dict.fromkeys(filenames))


def _load_readable_external_candidates(
    spectra_dir: str | Path,
    *,
    cache_root: str | Path | None = None,
    opus_axis_mode: str = OPUS_NATIVE,
) -> tuple[
    dict[str, tuple[np.ndarray, np.ndarray]],
    OpusCacheStats,
]:
    directory = Path(spectra_dir).expanduser()
    if not directory.is_dir():
        raise FileNotFoundError(
            f"OPUS directory not found: {directory}"
        )

    candidates = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and not path.name.startswith(".")
        ),
        key=lambda path: path.name,
    )
    if not candidates:
        raise ValueError(
            "The selected folder does not contain any files."
        )

    raw: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    hits = 0
    misses = 0
    failures: list[tuple[str, str]] = []
    cache_path = None

    for path in candidates:
        try:
            loaded, stats = load_opus_spectra_cached(
                directory,
                [path.name],
                cache_root=cache_root,
                opus_axis_mode=opus_axis_mode,
            )
        except Exception as exc:
            failures.append((path.name, str(exc)))
            continue

        raw.update(loaded)
        hits += int(stats.hits)
        misses += int(stats.misses)
        if stats.cache_path is not None:
            cache_path = stats.cache_path

    if not raw:
        detail = (
            f" First file checked: {failures[0][0]} ({failures[0][1]})"
            if failures
            else ""
        )
        raise ValueError(
            "No readable Bruker OPUS files were found in the selected folder. "
            "Numeric extensions such as .0 or .1 are supported, and files with "
            "other names are also accepted when they contain readable OPUS data."
            + detail
        )

    return raw, OpusCacheStats(
        hits=hits,
        misses=misses,
        requested=len(raw),
        cache_path=cache_path,
    )


def load_external_opus_library(
    spectra_dir: str | Path,
    *,
    filenames: list[str] | tuple[str, ...] | None = None,
    cache_root: str | Path | None = None,
    opus_axis_mode: str = OPUS_NATIVE,
    crop_min_cm1: float | None = None,
    crop_max_cm1: float | None = None,
    coverage: dict | None = None,
) -> tuple[
    dict[str, np.ndarray],
    np.ndarray,
    object,
]:
    """Load and align an external OPUS library.

    When filenames are supplied by an external-validation reference table, load
    exactly those files regardless of filename extension. Prediction-only mode
    keeps the fast numeric-extension path, then falls back to probing regular
    files for readable Bruker OPUS data when necessary.
    """
    if filenames is not None:
        requested = list(
            dict.fromkeys(
                str(name).strip()
                for name in filenames
                if str(name).strip()
            )
        )
        if not requested:
            raise ValueError(
                "The external reference does not contain any OPUS file names."
            )
        raw, cache_stats = load_opus_spectra_cached(
            spectra_dir,
            requested,
            cache_root=cache_root,
            opus_axis_mode=opus_axis_mode,
        )
    else:
        files = list_opus_files(spectra_dir)
        if files:
            raw, cache_stats = load_opus_spectra_cached(
                spectra_dir,
                [path.name for path in files],
                cache_root=cache_root,
                opus_axis_mode=opus_axis_mode,
            )
        else:
            raw, cache_stats = _load_readable_external_candidates(
                spectra_dir,
                cache_root=cache_root,
                opus_axis_mode=opus_axis_mode,
            )

    if coverage is not None:
        coverage["native"] = {
            name: _axis_summary(axis) for name, (_, axis) in raw.items()
        }
    if crop_min_cm1 is not None or crop_max_cm1 is not None:
        for name, (values, axis) in raw.items():
            try:
                raw[name] = crop_spectrum(values, axis, crop_min_cm1, crop_max_cm1)
            except ValueError as exc:
                raise ValueError(f"Cannot crop {name}: {exc}") from exc

    if coverage is not None:
        coverage["effective"] = {
            name: _axis_summary(axis) for name, (_, axis) in raw.items()
        }
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


def _axis_summary(axis):
    axis = validate_wavenumbers(np.asarray(axis, dtype=float))
    intervals = np.abs(np.diff(axis))
    return {
        "minimum": float(axis.min()), "maximum": float(axis.max()),
        "points": int(len(axis)), "median spacing": float(np.median(intervals)),
        "direction": "descending" if axis[0] > axis[-1] else "ascending",
    }


def spectral_compatibility(model_axis, aligned_axis, coverage=None, *,
                           mode="Automatic", manual_tolerance=0.25, automatic_limit=10.0):
    """Calculate actual model-grid coverage after alignment and any input crop."""
    model_axis = validate_wavenumbers(np.asarray(model_axis, dtype=float))
    aligned_axis = validate_wavenumbers(np.asarray(aligned_axis, dtype=float))
    model = _axis_summary(model_axis)
    external = _axis_summary(aligned_axis)
    if mode not in {"Automatic", "Manual"}:
        raise ValueError("Unknown endpoint extrapolation mode.")
    if any(not np.isfinite(v) or v < 0 for v in (manual_tolerance, automatic_limit)):
        raise ValueError("Extrapolation limits must be finite and non-negative.")
    lower = max(0., external["minimum"] - model["minimum"])
    upper = max(0., model["maximum"] - external["maximum"])
    required = max(lower, upper)
    limit = automatic_limit if mode == "Automatic" else manual_tolerance
    tolerance = (
        min(limit, max(0.25, math.ceil(required * 100) / 100, required))
        if mode == "Automatic" else manual_tolerance
    )
    overlap_low = max(model["minimum"], external["minimum"])
    overlap_high = min(model["maximum"], external["maximum"])
    native = (coverage or {}).get("native", {})
    effective = (coverage or {}).get("effective", {})
    outside = (model_axis < external["minimum"]) | (model_axis > external["maximum"])
    missing = int(outside.sum())
    if overlap_low >= overlap_high:
        reason = "No usable overlapping wavenumber interval."
    elif required > limit:
        reason = f"Required extrapolation {required:.6g} exceeds limit {limit:.6g} cm⁻¹."
    else:
        reason = "Compatible with endpoint extrapolation" if required else "Full coverage"
    compatible = overlap_low < overlap_high and required <= limit
    file_rows = []
    common_low = max((r["minimum"] for r in effective.values()), default=external["minimum"])
    common_high = min((r["maximum"] for r in effective.values()), default=external["maximum"])
    for name, row in effective.items():
        original = native.get(name, row)
        file_rows.append({
            "File Name": name,
            "Native minimum": original["minimum"], "Native maximum": original["maximum"],
            "Native points": original["points"],
            "Native median spacing": original["median spacing"],
            "Native direction": original["direction"],
            "Effective minimum": row["minimum"], "Effective maximum": row["maximum"],
            "Limits common lower bound": row["minimum"] == common_low,
            "Limits common upper bound": row["maximum"] == common_high,
        })
    metadata = {
        "Model minimum (cm⁻¹)": model["minimum"], "Model maximum (cm⁻¹)": model["maximum"],
        "Model grid points": model["points"], "Model grid direction": model["direction"],
        "Model median spacing (cm⁻¹)": model["median spacing"],
        "Aligned minimum (cm⁻¹)": external["minimum"],
        "Aligned maximum (cm⁻¹)": external["maximum"],
        "Aligned grid points": external["points"],
        "Aligned grid direction": external["direction"],
        "Aligned median spacing (cm⁻¹)": external["median spacing"],
        "Common measured minimum after crop (cm⁻¹)": common_low,
        "Common measured maximum after crop (cm⁻¹)": common_high,
        "Suggested overlap minimum (cm⁻¹)": overlap_low if overlap_low < overlap_high else None,
        "Suggested overlap maximum (cm⁻¹)": overlap_high if overlap_low < overlap_high else None,
        "Lower endpoint gap (cm⁻¹)": lower, "Upper endpoint gap (cm⁻¹)": upper,
        "Required extrapolation (cm⁻¹)": required,
        "Endpoint extrapolation mode": mode,
        "Automatic extrapolation limit (cm⁻¹)": automatic_limit if mode == "Automatic" else None,
        "Maximum endpoint extrapolation (cm⁻¹)": tolerance,
        "Extrapolated model points": missing,
        "Extrapolated model points (%)": 100 * missing / len(model_axis),
        "Model-grid interpolation needed": not np.array_equal(model_axis, aligned_axis),
        "Extrapolation method": "Linear" if missing else "None",
        "Spectral range compatible": compatible, "Compatibility reason": reason,
    }
    signature = hashlib.sha256(json.dumps(
        [metadata, file_rows, model_axis.tolist(), aligned_axis.tolist()],
        sort_keys=True, allow_nan=False,
    ).encode()).hexdigest()
    return {
        "metadata": metadata, "files": file_rows, "compatible": compatible,
        "requires_confirmation": required > 0.25, "tolerance": tolerance,
        "signature": signature, "reason": reason,
        "model_axis": model_axis, "aligned_axis": aligned_axis,
    }


class PredictionCompatibilityError(ValueError):
    def __init__(self, report, message):
        self.report = report
        super().__init__(message)


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
    opus_axis_mode: str | None = None,
    crop_min_cm1: float | None = None,
    crop_max_cm1: float | None = None,
    extrapolation_mode: str = "Manual",
    automatic_limit_cm1: float = 10.0,
    inspect_only: bool = False,
    require_confirmation: bool = False,
    confirmed_signature: str | None = None,
) -> dict:
    bundle = load_model_bundle(model_path)
    saved_axis_mode = bundle.get("opus_axis_mode", OPUS_LEGACY)
    axis_mode = saved_axis_mode if opus_axis_mode is None else opus_axis_mode
    if axis_mode not in (OPUS_NATIVE, OPUS_LEGACY):
        raise ValueError(f"Unknown OPUS axis mode: {axis_mode}")
    reference_filenames = (
        _reference_filenames(reference)
        if reference is not None
        else None
    )
    coverage = {}
    spectra, raw_wavenumbers, cache_stats = (
        load_external_opus_library(
            spectra_dir,
            filenames=reference_filenames,
            cache_root=cache_root,
            opus_axis_mode=axis_mode,
            crop_min_cm1=crop_min_cm1,
            crop_max_cm1=crop_max_cm1,
            coverage=coverage,
        )
    )
    compatibility = spectral_compatibility(
        bundle["wavenumbers"], raw_wavenumbers, coverage,
        mode=extrapolation_mode, manual_tolerance=max_extrapolation_cm1,
        automatic_limit=automatic_limit_cm1,
    )
    if inspect_only:
        return {"compatibility": compatibility}
    if not compatibility["compatible"]:
        raise PredictionCompatibilityError(compatibility, compatibility["reason"])
    confirmed = confirmed_signature == compatibility["signature"]
    if (extrapolation_mode == "Automatic" or require_confirmation) and (
        compatibility["requires_confirmation"] and not confirmed
    ):
        raise PredictionCompatibilityError(
            compatibility, "Review and confirm the calculated endpoint extrapolation."
        )
    max_extrapolation_cm1 = compatibility["tolerance"]
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
        "compatibility": compatibility,
        "input_metadata": {
            **compatibility["metadata"],
            "Endpoint extrapolation confirmed": confirmed
            if compatibility["requires_confirmation"] else "Not required",
            "Model OPUS axis mode": saved_axis_mode,
            "Prediction OPUS axis mode": axis_mode,
            "Crop minimum (cm⁻¹)": crop_min_cm1,
            "Crop maximum (cm⁻¹)": crop_max_cm1,
            "Aligned minimum (cm⁻¹)": float(raw_wavenumbers.min()),
            "Aligned maximum (cm⁻¹)": float(raw_wavenumbers.max()),
            "Maximum endpoint extrapolation (cm⁻¹)": max_extrapolation_cm1,
        },
    }



def save_prediction_results(
    replicate: pd.DataFrame,
    sample: pd.DataFrame,
    metrics: dict,
    bundle: dict,
    output_path: str | Path,
    model_path: str | Path,
    reference_sheet: str,
    *,
    input_metadata: dict | None = None,
    compatibility: dict | None = None,
) -> Path:
    """Save predictions and model metadata using the authoritative script layout."""
    output_path = Path(output_path).expanduser()
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    metrics_df = pd.DataFrame(
        [
            {
                "Metric": key,
                "Value": value,
            }
            for key, value in metrics.items()
        ]
    )
    model_info = pd.DataFrame(
        [
            {
                "Field": "Source model",
                "Value": str(model_path),
            },
            {
                "Field": "Reference sheet",
                "Value": reference_sheet,
            },
            {
                "Field": "Property",
                "Value": bundle.get(
                    "property_name",
                    "",
                ),
            },
            {
                "Field": "Units",
                "Value": bundle.get(
                    "units",
                    "",
                ),
            },
            {
                "Field": "Preprocessing",
                "Value": bundle.get(
                    "selected_preprocessing",
                    "",
                ),
            },
            {
                "Field": "PLS rank",
                "Value": bundle.get(
                    "selected_rank",
                    "",
                ),
            },
            {
                "Field": "Response transform",
                "Value": bundle.get(
                    "response_transform",
                    "",
                ),
            },
            {
                "Field": "CO2 excluded",
                "Value": bundle.get(
                    "exclude_co2",
                    "",
                ),
            },
            *(
                {"Field": key, "Value": value}
                for key, value in (input_metadata or {}).items()
            ),
        ]
    )

    with pd.ExcelWriter(
        output_path,
        engine="openpyxl",
    ) as writer:
        replicate.to_excel(
            writer,
            sheet_name="Replicate Predictions",
            index=False,
        )
        sample.to_excel(
            writer,
            sheet_name="Sample Predictions",
            index=False,
        )
        metrics_df.to_excel(
            writer,
            sheet_name="Metrics",
            index=False,
        )
        model_info.to_excel(
            writer,
            sheet_name="Model Info",
            index=False,
        )
        if compatibility is not None:
            pd.DataFrame(compatibility["files"]).to_excel(
                writer, sheet_name="Spectral Coverage", index=False
            )
            pd.DataFrame({
                "Model wavenumber (cm⁻¹)": pd.Series(compatibility["model_axis"]),
                "Aligned external wavenumber (cm⁻¹)": pd.Series(compatibility["aligned_axis"]),
            }).to_excel(writer, sheet_name="Wavenumber Grid", index=False)

    return output_path
