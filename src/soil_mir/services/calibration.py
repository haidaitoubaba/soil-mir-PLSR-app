from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from soil_mir.config import ColumnConfig
from soil_mir.io.cache import load_opus_spectra_cached
from soil_mir.io.opus import align_spectral_library
from soil_mir.io.reference import (
    load_property_metadata,
    read_property_sheet,
)
from soil_mir.modeling import fit_calibration_model
from soil_mir.regions import prepare_region_config
from soil_mir.transforms import apply_transform
from soil_mir.validation import (
    numerical_thread_context,
    outer_splits,
    run_validation,
)


@dataclass(frozen=True)
class CalibrationDataset:
    X: np.ndarray
    y: np.ndarray
    sample_ids: np.ndarray
    group_labels: np.ndarray
    wavenumbers: np.ndarray
    property_name: str
    units: str
    transform: str
    exclude_co2: bool
    rows: int
    unique_samples: int
    reference_filter_min: float | None = None
    reference_filter_max: float | None = None
    excluded_reference_rows: int = 0
    excluded_reference_samples: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_path: str = ""
    raw_wavenumber_min: float | None = None
    raw_wavenumber_max: float | None = None
    shared_wavenumber_min: float | None = None
    shared_wavenumber_max: float | None = None
    alignment_reference_points: int = 0
    shared_spectral_points: int = 0
    endpoint_trimmed_points: int = 0
    group_column_present: bool = False
    group_labels_complete: bool = False
    group_count: int = 0
    missing_group_samples: int = 0


def _normalise_group_labels(
    frame: pd.DataFrame,
    columns: ColumnConfig,
) -> tuple[np.ndarray, bool, bool, int, int]:
    """Keep all reference rows while normalising optional group metadata."""
    if columns.group not in frame.columns:
        return (
            np.full(len(frame), "", dtype=object),
            False,
            False,
            0,
            int(frame[columns.sample_id].nunique()),
        )

    labels = (
        frame[columns.group]
        .where(frame[columns.group].notna(), "")
        .astype(str)
        .str.strip()
        .copy()
    )
    samples = frame[columns.sample_id].astype(str)

    for sample in samples.unique():
        sample_mask = samples == sample
        known = labels.loc[
            sample_mask & (labels != "")
        ].unique()
        if len(known) > 1:
            raise ValueError(
                f"Sample {sample!r} has conflicting Group values."
            )
        if len(known) == 1:
            labels.loc[
                sample_mask & (labels == "")
            ] = known[0]

    missing_sample_mask = (
        pd.DataFrame(
            {
                "Sample": samples,
                "Group": labels,
            }
        )
        .groupby("Sample")["Group"]
        .first()
        .eq("")
    )
    missing_group_samples = int(
        missing_sample_mask.sum()
    )
    complete = bool(
        missing_group_samples == 0
        and len(labels) > 0
    )
    group_count = int(
        labels[labels != ""].nunique()
    )
    return (
        labels.to_numpy(dtype=object),
        True,
        complete,
        group_count,
        missing_group_samples,
    )


def load_calibration_dataset(
    spectra_dir: str | Path,
    reference_excel: str | Path,
    property_sheet: str,
    wn_min: float,
    wn_max: float,
    fallback_exclude_co2: bool,
    co2_min: float = 2300.0,
    co2_max: float = 2400.0,
    cache_root: str | Path | None = None,
    ref_min: float | None = None,
    ref_max: float | None = None,
) -> CalibrationDataset:
    columns = ColumnConfig()
    frame = read_property_sheet(
        reference_excel,
        property_sheet,
        columns,
    )
    required = [
        columns.sample_id,
        columns.reference_value,
        columns.reference_file,
    ]
    frame = frame.dropna(subset=required).copy()
    if frame.empty:
        raise ValueError(
            f"{property_sheet} has no complete reference rows."
        )

    if ref_min is not None:
        ref_min = float(ref_min)
        if not np.isfinite(ref_min):
            raise ValueError("ref_min must be finite or None.")
    if ref_max is not None:
        ref_max = float(ref_max)
        if not np.isfinite(ref_max):
            raise ValueError("ref_max must be finite or None.")
    if (
        ref_min is not None
        and ref_max is not None
        and ref_min > ref_max
    ):
        raise ValueError("ref_min must not exceed ref_max.")

    reference_values = frame[
        columns.reference_value
    ].to_numpy(dtype=float)
    include = np.ones(len(frame), dtype=bool)
    if ref_min is not None:
        include &= reference_values >= ref_min
    if ref_max is not None:
        include &= reference_values <= ref_max

    excluded = frame.loc[~include]
    excluded_reference_rows = int((~include).sum())
    excluded_reference_samples = int(
        excluded[columns.sample_id].nunique()
    )
    frame = frame.loc[include].copy()

    if frame.empty:
        raise ValueError(
            f"{property_sheet} has no rows inside the selected "
            "reference-value range."
        )

    metadata = load_property_metadata(reference_excel)
    property_metadata = metadata.get(property_sheet, {})
    transform = str(property_metadata.get("transform", "none"))
    units = str(property_metadata.get("units", ""))
    metadata_exclude = property_metadata.get("exclude_co2")
    exclude_co2 = (
        fallback_exclude_co2
        if metadata_exclude is None
        else bool(metadata_exclude)
    )

    filenames = frame[columns.reference_file].astype(str).tolist()
    spectra_by_name, cache_stats = load_opus_spectra_cached(
        spectra_dir,
        filenames,
        cache_root=cache_root,
    )

    raw_spectra = {
        name: values
        for name, (values, _axis) in spectra_by_name.items()
    }
    raw_axes = {
        name: axis
        for name, (_values, axis) in spectra_by_name.items()
    }
    axis_lengths = [
        len(axis)
        for axis in raw_axes.values()
    ]
    alignment_reference_points = Counter(
        axis_lengths
    ).most_common(1)[0][0]
    raw_wavenumber_min = min(
        float(np.min(axis))
        for axis in raw_axes.values()
    )
    raw_wavenumber_max = max(
        float(np.max(axis))
        for axis in raw_axes.values()
    )

    aligned_spectra, target_axis = align_spectral_library(
        raw_spectra,
        raw_axes,
    )
    shared_spectral_points = int(
        len(target_axis)
    )
    endpoint_trimmed_points = int(
        alignment_reference_points
        - shared_spectral_points
    )
    matrices = [
        aligned_spectra[filename]
        for filename in filenames
    ]

    if not matrices:
        raise ValueError("No spectra could be loaded.")

    X = np.vstack(matrices)
    y = frame[columns.reference_value].to_numpy(dtype=float)
    sample_ids = frame[columns.sample_id].astype(str).to_numpy()
    (
        group_labels,
        group_column_present,
        group_labels_complete,
        group_count,
        missing_group_samples,
    ) = _normalise_group_labels(
        frame,
        columns,
    )

    mask = (
        (target_axis >= wn_min)
        & (target_axis <= wn_max)
    )
    if exclude_co2:
        mask &= ~(
            (target_axis >= co2_min)
            & (target_axis <= co2_max)
        )
    if mask.sum() < 11:
        raise ValueError(
            "The retained spectral range is too short."
        )

    return CalibrationDataset(
        X=X[:, mask],
        y=y,
        sample_ids=sample_ids,
        group_labels=group_labels,
        wavenumbers=target_axis[mask],
        property_name=property_sheet,
        units=units,
        transform=transform,
        exclude_co2=exclude_co2,
        rows=len(frame),
        unique_samples=int(pd.Series(sample_ids).nunique()),
        reference_filter_min=ref_min,
        reference_filter_max=ref_max,
        excluded_reference_rows=excluded_reference_rows,
        excluded_reference_samples=excluded_reference_samples,
        cache_hits=cache_stats.hits,
        cache_misses=cache_stats.misses,
        cache_path=(
            str(cache_stats.cache_path)
            if cache_stats.cache_path is not None
            else ""
        ),
        raw_wavenumber_min=raw_wavenumber_min,
        raw_wavenumber_max=raw_wavenumber_max,
        shared_wavenumber_min=float(
            np.min(target_axis)
        ),
        shared_wavenumber_max=float(
            np.max(target_axis)
        ),
        alignment_reference_points=(
            alignment_reference_points
        ),
        shared_spectral_points=(
            shared_spectral_points
        ),
        endpoint_trimmed_points=(
            endpoint_trimmed_points
        ),
        group_column_present=(
            group_column_present
        ),
        group_labels_complete=(
            group_labels_complete
        ),
        group_count=group_count,
        missing_group_samples=(
            missing_group_samples
        ),
    )


def run_validation_analysis(
    dataset: CalibrationDataset,
    *,
    method: str,
    max_rank: int,
    region_search_n_windows: int,
    rmsecv_tolerance_pct: float,
    sg_window: int,
    sg_polyorder: int,
    random_seed: int,
    internal_cv_folds: int,
    outer_cv_folds: int,
    n_repeats: int,
    validation_fraction: float,
    ks_representation: str,
    ks_pca_variance: float,
    wn_min: float,
    wn_max: float,
    outer_n_jobs: int = 1,
    inner_thread_limit: int | None = 1,
    use_group_stratification: bool = True,
    progress_callback=None,
    cancel_event=None,
) -> dict:
    cfg = {
        "wn_min": float(wn_min),
        "wn_max": float(wn_max),
        "exclude_co2": dataset.exclude_co2,
        "co2_exclude_min": 2300.0,
        "co2_exclude_max": 2400.0,
        "sg_window": int(sg_window),
        "sg_polyorder": int(sg_polyorder),
        "max_rank": int(max_rank),
        "region_search_n_windows": int(region_search_n_windows),
        "rmsecv_tolerance_pct": float(rmsecv_tolerance_pct),
        "outlier_max_pct": 0.0,
        "random_seed": int(random_seed),
        "internal_cv_folds": int(internal_cv_folds),
        "outer_cv_folds": int(outer_cv_folds),
        "n_repeats": int(n_repeats),
        "validation_fraction": float(validation_fraction),
        "ks_representation": ks_representation,
        "ks_pca_variance": float(ks_pca_variance),
        "outer_n_jobs": int(outer_n_jobs),
        "inner_thread_limit": (
            None
            if inner_thread_limit is None
            else int(inner_thread_limit)
        ),
        "use_group_stratification": bool(
            use_group_stratification
        ),
        "method": method,
        "property_name": dataset.property_name,
        "units": dataset.units,
        "transform": dataset.transform,
        "ref_min": dataset.reference_filter_min,
        "ref_max": dataset.reference_filter_max,
        "excluded_reference_rows": dataset.excluded_reference_rows,
        "excluded_reference_samples": dataset.excluded_reference_samples,
        "model_role": "final_all_samples",
        "group_column_present": dataset.group_column_present,
        "group_labels_complete": dataset.group_labels_complete,
        "group_count": dataset.group_count,
        "missing_group_samples": dataset.missing_group_samples,
    }
    cfg = prepare_region_config(
        cfg,
        dataset.wavenumbers,
    )

    result = run_validation(
        dataset.X,
        dataset.y,
        dataset.sample_ids,
        dataset.group_labels,
        dataset.wavenumbers,
        cfg,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
    )
    result.update(
        {
            "property": dataset.property_name,
            "method": method,
            "dataset": dataset,
            "config": cfg,
        }
    )
    return result


def refit_final_model_only(
    dataset: CalibrationDataset,
    *,
    method: str,
    max_rank: int,
    region_search_n_windows: int,
    rmsecv_tolerance_pct: float,
    sg_window: int,
    sg_polyorder: int,
    random_seed: int,
    internal_cv_folds: int,
    outer_cv_folds: int,
    n_repeats: int,
    validation_fraction: float,
    ks_representation: str,
    ks_pca_variance: float,
    wn_min: float,
    wn_max: float,
    outer_n_jobs: int = 1,
    inner_thread_limit: int | None = 1,
    use_group_stratification: bool = True,
) -> dict:
    """Refit only the final all-data model at a selected tolerance.

    No outer validation splits are rerun. The internal final-calibration
    search is rerun on all eligible calibration samples so the resulting
    model follows the same scientific selection path as a full run.
    """
    cfg = {
        "wn_min": float(wn_min),
        "wn_max": float(wn_max),
        "exclude_co2": dataset.exclude_co2,
        "co2_exclude_min": 2300.0,
        "co2_exclude_max": 2400.0,
        "sg_window": int(sg_window),
        "sg_polyorder": int(sg_polyorder),
        "max_rank": int(max_rank),
        "region_search_n_windows": int(
            region_search_n_windows
        ),
        "rmsecv_tolerance_pct": float(
            rmsecv_tolerance_pct
        ),
        "outlier_max_pct": 0.0,
        "random_seed": int(random_seed),
        "internal_cv_folds": int(
            internal_cv_folds
        ),
        "outer_cv_folds": int(
            outer_cv_folds
        ),
        "n_repeats": int(n_repeats),
        "validation_fraction": float(
            validation_fraction
        ),
        "ks_representation": str(
            ks_representation
        ),
        "ks_pca_variance": float(
            ks_pca_variance
        ),
        "outer_n_jobs": int(
            outer_n_jobs
        ),
        "inner_thread_limit": (
            None
            if inner_thread_limit is None
            else int(inner_thread_limit)
        ),
        "use_group_stratification": bool(
            use_group_stratification
        ),
        "method": str(method),
        "property_name": dataset.property_name,
        "units": dataset.units,
        "transform": dataset.transform,
        "ref_min": dataset.reference_filter_min,
        "ref_max": dataset.reference_filter_max,
        "excluded_reference_rows": (
            dataset.excluded_reference_rows
        ),
        "excluded_reference_samples": (
            dataset.excluded_reference_samples
        ),
        "model_role": "final_all_samples",
        "group_column_present": dataset.group_column_present,
        "group_labels_complete": dataset.group_labels_complete,
        "group_count": dataset.group_count,
        "missing_group_samples": dataset.missing_group_samples,
    }
    cfg = prepare_region_config(
        cfg,
        dataset.wavenumbers,
    )

    with numerical_thread_context(cfg):
        (
            final_model,
            final_settings,
            removed_samples,
            final_search,
        ) = fit_calibration_model(
            dataset.X,
            dataset.y,
            dataset.sample_ids,
            dataset.wavenumbers,
            cfg,
            dataset.group_labels,
        )

    final_model.update(
        artifact_role="final_only_refit",
        outer_validation_rerun=False,
        refit_tolerance_pct=float(
            rmsecv_tolerance_pct
        ),
    )
    return {
        "property": dataset.property_name,
        "method": str(method),
        "final_model": final_model,
        "final_settings": final_settings,
        "final_search": final_search,
        "removed_samples": list(
            removed_samples
        ),
        "config": cfg,
        "dataset": dataset,
        "refit_tolerance_pct": float(
            rmsecv_tolerance_pct
        ),
        "outer_validation_rerun": False,
    }


def preflight_validation_methods(
    dataset: CalibrationDataset,
    *,
    methods: list[str],
    max_rank: int,
    region_search_n_windows: int,
    rmsecv_tolerance_pct: float,
    sg_window: int,
    sg_polyorder: int,
    random_seed: int,
    internal_cv_folds: int,
    outer_cv_folds: int,
    n_repeats: int,
    validation_fraction: float,
    ks_representation: str,
    ks_pca_variance: float,
    wn_min: float,
    wn_max: float,
    outer_n_jobs: int = 1,
    inner_thread_limit: int | None = 1,
    use_group_stratification: bool = True,
) -> pd.DataFrame:
    apply_transform(
        dataset.y,
        dataset.transform,
    )
    records = []

    for method in methods:
        group_request = (
            "Required"
            if method == "logo"
            else (
                "Yes"
                if (
                    method in ("kfold", "monte_carlo")
                    and use_group_stratification
                )
                else "No"
            )
        )
        cfg = {
            "wn_min": float(wn_min),
            "wn_max": float(wn_max),
            "exclude_co2": dataset.exclude_co2,
            "co2_exclude_min": 2300.0,
            "co2_exclude_max": 2400.0,
            "sg_window": int(sg_window),
            "sg_polyorder": int(sg_polyorder),
            "max_rank": int(max_rank),
            "region_search_n_windows": int(
                region_search_n_windows
            ),
            "rmsecv_tolerance_pct": float(
                rmsecv_tolerance_pct
            ),
            "outlier_max_pct": 0.0,
            "random_seed": int(random_seed),
            "internal_cv_folds": int(
                internal_cv_folds
            ),
            "outer_cv_folds": int(
                outer_cv_folds
            ),
            "n_repeats": int(n_repeats),
            "validation_fraction": float(
                validation_fraction
            ),
            "ks_representation": ks_representation,
            "ks_pca_variance": float(
                ks_pca_variance
            ),
            "outer_n_jobs": int(
                outer_n_jobs
            ),
            "inner_thread_limit": (
                None
                if inner_thread_limit is None
                else int(
                    inner_thread_limit
                )
            ),
            "method": method,
            "property_name": dataset.property_name,
            "units": dataset.units,
            "transform": dataset.transform,
            "ref_min": dataset.reference_filter_min,
            "ref_max": dataset.reference_filter_max,
            "excluded_reference_rows": dataset.excluded_reference_rows,
            "excluded_reference_samples": dataset.excluded_reference_samples,
            "model_role": "final_all_samples",
            "use_group_stratification": bool(
                use_group_stratification
            ),
        "group_column_present": dataset.group_column_present,
        "group_labels_complete": dataset.group_labels_complete,
        "group_count": dataset.group_count,
        "missing_group_samples": dataset.missing_group_samples,
        }

        try:
            cfg = prepare_region_config(
                cfg,
                dataset.wavenumbers,
            )
            splits, split_info = outer_splits(
                dataset.X,
                dataset.sample_ids,
                dataset.group_labels,
                cfg,
            )
        except Exception as exc:
            records.append(
                {
                    "Property": dataset.property_name,
                    "Method": method,
                    "Status": "Fail",
                    "Samples": dataset.unique_samples,
                    "Groups": dataset.group_count,
                    "Group data": (
                        "Complete"
                        if dataset.group_labels_complete
                        else (
                            "Partial"
                            if dataset.group_column_present
                            else "Not provided"
                        )
                    ),
                    "Group stratification requested": group_request,
                    "Group stratification used": "No",
                    "Outer splits": 0,
                    "Details": str(exc),
                }
            )
        else:
            records.append(
                {
                    "Property": dataset.property_name,
                    "Method": method,
                    "Status": "Pass",
                    "Samples": dataset.unique_samples,
                    "Groups": dataset.group_count,
                    "Group data": (
                        "Complete"
                        if dataset.group_labels_complete
                        else (
                            "Partial"
                            if dataset.group_column_present
                            else "Not provided"
                        )
                    ),
                    "Group stratification requested": group_request,
                    "Group stratification used": (
                        "Yes"
                        if split_info.get(
                            "group_stratification_used",
                            False,
                        )
                        else "No"
                    ),
                    "Outer splits": len(splits),
                    "Details": split_info.get(
                        "splitter",
                        method,
                    ),
                }
            )

    return pd.DataFrame(records)
