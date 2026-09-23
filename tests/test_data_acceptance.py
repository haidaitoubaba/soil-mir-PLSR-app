from pathlib import Path

import numpy as np
import pandas as pd

from soil_mir.services import acceptance
from soil_mir.services.calibration import (
    CalibrationDataset,
)


def _summary(property_name):
    return type(
        "Summary",
        (),
        {
            "sheet": property_name,
            "rows": 6,
            "unique_samples": 2,
            "groups": 2,
            "missing_reference_values": 0,
            "zero_reference_values": 0,
            "negative_reference_values": 0,
            "duplicate_rows": 0,
        },
    )()


def _dataset(property_name, cache_hits, cache_misses):
    return CalibrationDataset(
        X=np.ones((6, 32)),
        y=np.ones(6),
        sample_ids=np.array(
            ["A", "A", "A", "B", "B", "B"]
        ),
        group_labels=np.array(
            ["1", "1", "1", "2", "2", "2"]
        ),
        wavenumbers=np.linspace(
            600,
            4000,
            32,
        ),
        property_name=property_name,
        units="unit",
        transform="sqrt",
        exclude_co2=False,
        rows=6,
        unique_samples=2,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
    )


def test_acceptance_reuses_shared_files_and_writes_report(
    tmp_path,
    monkeypatch,
):
    filenames = [
        "A_1.0",
        "A_2.0",
        "A_3.0",
        "B_1.0",
        "B_2.0",
        "B_3.0",
    ]

    monkeypatch.setattr(
        acceptance,
        "load_property_metadata",
        lambda _path: {},
    )
    monkeypatch.setattr(
        acceptance,
        "summarize_property",
        lambda _path, prop, metadata=None: _summary(prop),
    )
    monkeypatch.setattr(
        acceptance,
        "read_property_sheet",
        lambda _path, _prop: pd.DataFrame(
            {
                "File Name": filenames,
                "Sample": [
                    "A",
                    "A",
                    "A",
                    "B",
                    "B",
                    "B",
                ],
                "Reference Value": [
                    0.0,
                    0.0,
                    0.0,
                    2.0,
                    2.0,
                    2.0,
                ],
            }
        ),
    )

    calls = []

    def fake_load(
        spectra_dir,
        reference_excel,
        property_name,
        **kwargs,
    ):
        del spectra_dir, reference_excel, kwargs
        calls.append(property_name)
        if len(calls) == 1:
            return _dataset(
                property_name,
                cache_hits=0,
                cache_misses=6,
            )
        return _dataset(
            property_name,
            cache_hits=6,
            cache_misses=0,
        )

    monkeypatch.setattr(
        acceptance,
        "load_calibration_dataset",
        fake_load,
    )

    result = acceptance.run_data_acceptance(
        tmp_path / "spectra",
        tmp_path / "reference.xlsx",
        tmp_path / "results",
        properties=[
            "202_STC",
            "202_STN",
        ],
    )

    table = result["properties"].set_index(
        "Property"
    )
    assert table.loc[
        "202_STC",
        "Cache misses",
    ] == 6
    assert table.loc[
        "202_STN",
        "Cache hits",
    ] == 6

    alignment = result["alignment"].iloc[0]
    assert bool(
        alignment["Identical file set"]
    )
    assert alignment["Shared files"] == 6
    assert table.loc[
        "202_STC",
        "Zero ref samples",
    ] == "A"
    assert table.loc[
        "202_STN",
        "Zero ref samples",
    ] == "A"
    assert Path(
        result["report_path"]
    ).is_file()
