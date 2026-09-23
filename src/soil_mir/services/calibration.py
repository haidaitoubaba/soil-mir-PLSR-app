from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from soil_mir.config import ColumnConfig
from soil_mir.io.opus import read_opus_spectrum, resample_spectrum
from soil_mir.io.reference import (
    load_property_metadata,
    read_property_sheet,
)
from soil_mir.modeling import fit_calibration_model
from soil_mir.regions import prepare_region_config


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


def load_calibration_dataset(
    spectra_dir: str | Path,
    reference_excel: str | Path,
    property_sheet: str,
    wn_min: float,
    wn_max: float,
    fallback_exclude_co2: bool,
    co2_min: float = 2300.0,
    co2_max: float = 2400.0,
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
    transform = str(
        property_metadata.get("transform", "none")
    )
    units = str(
        property_metadata.get("units", "")
    )
    metadata_exclude = property_metadata.get("exclude_co2")
    exclude_co2 = (
        fallback_exclude_co2
        if metadata_exclude is None
        else bool(metadata_exclude)
    )

    spectra_dir = Path(spectra_dir)
    matrices = []
    target_axis = None
    missing = []

    for filename in frame[columns.reference_file].astype(str):
        path = spectra_dir / filename
        if not path.is_file():
            missing.append(filename)
            continue
        values, axis = read_opus_spectrum(path)
        if target_axis is None:
            target_axis = axis
        matrices.append(
            resample_spectrum(
                values,
                axis,
                target_axis,
            )
        )

    if missing:
        shown = ", ".join(missing[:8])
        raise FileNotFoundError(
            f"{len(missing)} referenced spectra are missing. "
            f"First files: {shown}"
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
        unique_samples=int(
            pd.Series(sample_ids).nunique()
        ),
    )


def run_calibration(
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
    wn_min: float,
    wn_max: float,
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
        "region_search_n_windows": int(
            region_search_n_windows
        ),
        "rmsecv_tolerance_pct": float(
            rmsecv_tolerance_pct
        ),
        "outlier_max_pct": 0.0,
        "random_seed": int(random_seed),
        "internal_cv_folds": int(internal_cv_folds),
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

    bundle, best, removed, search = fit_calibration_model(
        dataset.X,
        dataset.y,
        dataset.sample_ids,
        dataset.wavenumbers,
        cfg,
        dataset.group_labels,
    )
    return {
        "property": dataset.property_name,
        "method": method,
        "dataset": dataset,
        "bundle": bundle,
        "best": best,
        "removed_samples": removed,
        "search": search,
        "config": cfg,
    }
