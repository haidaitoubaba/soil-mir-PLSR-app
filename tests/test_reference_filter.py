from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from soil_mir.io.cache import OpusCacheStats
from soil_mir.services import calibration


def _workbook(path: Path):
    frame = pd.DataFrame(
        {
            "Sample": ["S0", "S1", "S2", "S3", "S4", "S5"],
            "Reference Value": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
            "File Name": [
                "S0.0",
                "S1.0",
                "S2.0",
                "S3.0",
                "S4.0",
                "S5.0",
            ],
            "Group": ["A", "A", "B", "B", "C", "C"],
        }
    )
    metadata = pd.DataFrame(
        {
            "Property": ["STC"],
            "Units": ["g C/kg soil"],
            "Transform": ["sqrt"],
            "Field": [202],
            "Exclude CO2": [False],
        }
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(
            writer,
            sheet_name="202_STC",
            index=False,
        )
        metadata.to_excel(
            writer,
            sheet_name="Property Metadata",
            index=False,
        )


def _fake_cache(_directory, filenames, cache_root=None):
    del cache_root
    axis = np.linspace(600, 4000, 32)
    spectra = {
        name: (
            np.full(
                len(axis),
                float(index + 1),
            ),
            axis,
        )
        for index, name in enumerate(filenames)
    }
    return spectra, OpusCacheStats(
        hits=0,
        misses=len(filenames),
        requested=len(filenames),
        cache_path=None,
    )


def test_reference_range_filters_before_spectra_loading(
    tmp_path,
    monkeypatch,
):
    workbook = tmp_path / "reference.xlsx"
    spectra = tmp_path / "spectra"
    spectra.mkdir()
    _workbook(workbook)

    requested = []

    def capture_cache(directory, filenames, cache_root=None):
        requested.extend(filenames)
        return _fake_cache(
            directory,
            filenames,
            cache_root=cache_root,
        )

    monkeypatch.setattr(
        calibration,
        "load_opus_spectra_cached",
        capture_cache,
    )

    dataset = calibration.load_calibration_dataset(
        spectra,
        workbook,
        "202_STC",
        wn_min=600,
        wn_max=4000,
        fallback_exclude_co2=False,
        ref_min=1.0,
        ref_max=4.0,
    )

    assert dataset.rows == 4
    assert dataset.unique_samples == 4
    assert dataset.excluded_reference_rows == 2
    assert dataset.excluded_reference_samples == 2
    assert dataset.reference_filter_min == 1.0
    assert dataset.reference_filter_max == 4.0
    assert set(dataset.sample_ids) == {
        "S1",
        "S2",
        "S3",
        "S4",
    }
    assert requested == [
        "S1.0",
        "S2.0",
        "S3.0",
        "S4.0",
    ]


def test_invalid_reference_range_is_rejected(
    tmp_path,
    monkeypatch,
):
    workbook = tmp_path / "reference.xlsx"
    spectra = tmp_path / "spectra"
    spectra.mkdir()
    _workbook(workbook)

    monkeypatch.setattr(
        calibration,
        "load_opus_spectra_cached",
        _fake_cache,
    )

    with pytest.raises(
        ValueError,
        match="ref_min must not exceed ref_max",
    ):
        calibration.load_calibration_dataset(
            spectra,
            workbook,
            "202_STC",
            wn_min=600,
            wn_max=4000,
            fallback_exclude_co2=False,
            ref_min=5.0,
            ref_max=1.0,
        )
