from pathlib import Path

import pandas as pd

from soil_mir.io.reference import (
    discover_property_sheets,
    load_property_metadata,
    read_property_sheet,
    summarize_property,
)


FIXTURE = Path(__file__).parent / "fixtures" / "soil_mir_202"
WORKBOOK = FIXTURE / "reference" / "reference_202_stc_stn.xlsx"


def test_fixture_discovers_only_requested_property_sheets():
    sheets = discover_property_sheets(WORKBOOK)
    assert sheets == ["202_STC", "202_STN"]


def test_fixture_has_shared_24_sample_design():
    stc = read_property_sheet(WORKBOOK, "202_STC")
    stn = read_property_sheet(WORKBOOK, "202_STN")
    assert len(stc) == 72
    assert len(stn) == 72
    assert stc["Sample"].nunique() == 24
    assert stn["Sample"].nunique() == 24
    assert set(stc["Sample"]) == set(stn["Sample"])
    assert stc["Group"].nunique() == 12
    assert stn["Group"].nunique() == 12
    assert stc.groupby("Sample").size().eq(3).all()
    assert stn.groupby("Sample").size().eq(3).all()


def test_metadata_is_property_specific():
    metadata = load_property_metadata(WORKBOOK)
    assert metadata["202_STC"]["units"] == "g C/kg soil"
    assert metadata["202_STC"]["transform"] == "sqrt"
    assert metadata["202_STC"]["exclude_co2"] is True
    assert metadata["202_STN"]["units"] == "g N/kg soil"
    assert metadata["202_STN"]["transform"] == "sqrt"
    assert metadata["202_STN"]["exclude_co2"] is False


def test_property_summary():
    metadata = load_property_metadata(WORKBOOK)
    summary = summarize_property(WORKBOOK, "202_STC", metadata=metadata)
    assert summary.rows == 72
    assert summary.unique_samples == 24
    assert summary.groups == 12
    assert summary.missing_reference_values == 0
    assert summary.zero_reference_values == 0
    assert summary.negative_reference_values == 0
    assert summary.reference_min > 0
    assert summary.reference_max > summary.reference_min


def test_reference_group_column_is_optional(tmp_path):
    workbook = tmp_path / "reference_no_group.xlsx"
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2"],
            "Reference Value": [1.0, 2.0],
            "File Name": ["S1.0", "S2.0"],
        }
    )
    with pd.ExcelWriter(
        workbook,
        engine="openpyxl",
    ) as writer:
        frame.to_excel(
            writer,
            sheet_name="STC",
            index=False,
        )

    assert discover_property_sheets(
        workbook
    ) == ["STC"]

    loaded = read_property_sheet(
        workbook,
        "STC",
    )
    assert "Group" not in loaded.columns

    summary = summarize_property(
        workbook,
        "STC",
    )
    assert summary.group_column_present is False
    assert summary.groups is None
    assert summary.missing_group_values == 0
