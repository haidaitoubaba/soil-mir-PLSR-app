from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from soil_mir.io.reference import (
    load_property_metadata,
    read_property_sheet,
    summarize_property,
)
from soil_mir.reporting import write_json
from soil_mir.services.calibration import (
    load_calibration_dataset,
)


def run_data_acceptance(
    spectra_dir: str | Path,
    reference_excel: str | Path,
    output_dir: str | Path,
    *,
    properties: list[str],
    wn_min: float = 600.0,
    wn_max: float = 4000.0,
    fallback_exclude_co2: bool = False,
) -> dict:
    if not properties:
        raise ValueError(
            "Select at least one property for data acceptance."
        )

    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_root = output_dir / ".soil_mir_cache"
    metadata = load_property_metadata(reference_excel)

    property_rows = []
    file_sets: dict[str, set[str]] = {}

    for property_name in properties:
        summary = summarize_property(
            reference_excel,
            property_name,
            metadata=metadata,
        )
        frame = read_property_sheet(
            reference_excel,
            property_name,
        )
        file_sets[property_name] = set(
            frame["File Name"].dropna().astype(str)
        )
        numeric_reference = pd.to_numeric(
            frame["Reference Value"],
            errors="coerce",
        )
        zero_samples = sorted(
            frame.loc[
                numeric_reference == 0,
                "Sample",
            ]
            .dropna()
            .astype(str)
            .unique()
        )
        negative_samples = sorted(
            frame.loc[
                numeric_reference < 0,
                "Sample",
            ]
            .dropna()
            .astype(str)
            .unique()
        )

        dataset = load_calibration_dataset(
            spectra_dir,
            reference_excel,
            property_name,
            wn_min=wn_min,
            wn_max=wn_max,
            fallback_exclude_co2=fallback_exclude_co2,
            cache_root=cache_root,
        )

        property_rows.append(
            {
                "Property": property_name,
                "Status": "Pass",
                "Reference rows": summary.rows,
                "Loaded spectra": dataset.rows,
                "Unique samples": dataset.unique_samples,
                "Groups": (
                    dataset.group_count
                    if dataset.group_column_present
                    else "Not provided"
                ),
                "Group data": (
                    "Complete"
                    if dataset.group_labels_complete
                    else (
                        "Partial"
                        if dataset.group_column_present
                        else "Not provided"
                    )
                ),
                "Missing group samples": (
                    dataset.missing_group_samples
                ),
                "Raw coverage min": (
                    dataset.raw_wavenumber_min
                ),
                "Raw coverage max": (
                    dataset.raw_wavenumber_max
                ),
                "Alignment reference points": (
                    dataset.alignment_reference_points
                ),
                "Shared coverage min": (
                    dataset.shared_wavenumber_min
                ),
                "Shared coverage max": (
                    dataset.shared_wavenumber_max
                ),
                "Shared spectral points": (
                    dataset.shared_spectral_points
                ),
                "Endpoint points trimmed": (
                    dataset.endpoint_trimmed_points
                ),
                "Final spectral points": int(
                    len(dataset.wavenumbers)
                ),
                "Final wavenumber min": float(
                    dataset.wavenumbers.min()
                ),
                "Final wavenumber max": float(
                    dataset.wavenumbers.max()
                ),
                "Transform": dataset.transform,
                "CO2 excluded": dataset.exclude_co2,
                "Missing refs": (
                    summary.missing_reference_values
                ),
                "Zero refs": (
                    summary.zero_reference_values
                ),
                "Zero ref samples": "; ".join(
                    zero_samples
                ),
                "Negative refs": (
                    summary.negative_reference_values
                ),
                "Negative ref samples": "; ".join(
                    negative_samples
                ),
                "Duplicate rows": (
                    summary.duplicate_rows
                ),
                "Cache hits": dataset.cache_hits,
                "Cache misses": dataset.cache_misses,
            }
        )

    pairwise = []
    names = list(properties)
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            first_files = file_sets[first]
            second_files = file_sets[second]
            pairwise.append(
                {
                    "Property A": first,
                    "Property B": second,
                    "A files": len(first_files),
                    "B files": len(second_files),
                    "Shared files": len(
                        first_files & second_files
                    ),
                    "Only A": len(
                        first_files - second_files
                    ),
                    "Only B": len(
                        second_files - first_files
                    ),
                    "Identical file set": (
                        first_files == second_files
                    ),
                }
            )

    report = {
        "version": 1,
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "spectra_dir": str(
            Path(spectra_dir).expanduser()
        ),
        "reference_excel": str(
            Path(reference_excel).expanduser()
        ),
        "properties": property_rows,
        "property_file_alignment": pairwise,
        "status": "Pass",
    }

    report_path = (
        output_dir
        / "Data_Acceptance_Report.json"
    )
    write_json(
        report_path,
        report,
    )

    return {
        "report": report,
        "properties": pd.DataFrame(
            property_rows
        ),
        "alignment": pd.DataFrame(
            pairwise
        ),
        "report_path": str(report_path),
    }
