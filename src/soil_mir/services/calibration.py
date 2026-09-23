from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from soil_mir.config import ColumnConfig
from soil_mir.io.cache import load_opus_spectra_cached
from soil_mir.io.opus import resample_spectrum
from soil_mir.io.reference import (
    load_property_metadata,
    read_property_sheet,
)
from soil_mir.regions import prepare_region_config
from soil_mir.transforms import apply_transform
from soil_mir.validation import outer_splits, run_validation


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
    cache_hits: int = 0
    cache_misses: int = 0
    cache_path: str = ""


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
        columns.group,
    ]
    frame = frame.dropna(subset=required).copy()
    if frame.empty:
        raise ValueError(
            f"{property_sheet} has no complete reference rows."
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

    matrices = []
    target_axis = None
    for filename in filenames:
        values, axis = spectra_by_name[filename]
        if target_axis is None:
            target_axis = axis
        matrices.append(
            resample_spectrum(
                values,
                axis,
                target_axis,
            )
        )

    if target_axis is None or not matrices:
        raise ValueError("No spectra could be loaded.")

    X = np.vstack(matrices)
    y = frame[columns.reference_value].to_numpy(dtype=float)
    sample_ids = frame[columns.sample_id].astype(str).to_numpy()
    group_labels = frame[columns.group].astype(str).to_numpy()

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
        cache_hits=cache_stats.hits,
        cache_misses=cache_stats.misses,
        cache_path=(
            str(cache_stats.cache_path)
            if cache_stats.cache_path is not None
            else ""
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
    progress_callback=None,
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
        "method": method,
        "property_name": dataset.property_name,
        "units": dataset.units,
        "transform": dataset.transform,
        "model_role": "final_all_samples",
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
) -> pd.DataFrame:
    apply_transform(
        dataset.y,
        dataset.transform,
    )
    records = []

    for method in methods:
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
            "method": method,
            "property_name": dataset.property_name,
            "units": dataset.units,
            "transform": dataset.transform,
            "model_role": "final_all_samples",
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
                    "Groups": int(
                        pd.Series(
                            dataset.group_labels
                        ).nunique()
                    ),
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
                    "Groups": int(
                        pd.Series(
                            dataset.group_labels
                        ).nunique()
                    ),
                    "Outer splits": len(splits),
                    "Details": split_info.get(
                        "splitter",
                        method,
                    ),
                }
            )

    return pd.DataFrame(records)
