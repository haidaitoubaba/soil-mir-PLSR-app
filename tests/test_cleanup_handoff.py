import json
from types import SimpleNamespace

import pytest

from soil_mir.cleanup.handoff import PropertyRetention, build_handoff, file_sha256


def test_cleanup_handoff_is_current_and_exclusions_are_property_specific(tmp_path):
    spectra = tmp_path / "spectra"
    spectra.mkdir()
    scan = spectra / "soil.0"
    scan.write_bytes(b"scan")
    export = tmp_path / "export"
    export.mkdir()
    workbook = export / "reference_cleaned.xlsx"
    workbook.write_bytes(b"cleaned workbook")
    workbook.with_suffix(".cleanup.json").write_text(
        json.dumps({"cleaned_sha256": file_sha256(workbook)}), encoding="utf-8"
    )

    row = {"File Name": scan.name, "Sample": "soil"}
    review = SimpleNamespace(
        revision=2,
        export_revision=2,
        last_export=export,
        state={
            "properties": {
                "TC": {"frame": [row], "decisions": {scan.name: {}}},
                "TN": {"frame": [row], "decisions": {}},
            },
            "spectra_sha256": {scan.name: file_sha256(scan)},
        },
    )
    handoff = build_handoff(review, str(spectra))
    assert handoff.properties == (
        PropertyRetention("TC", 0, 0),
        PropertyRetention("TN", 1, 1),
    )

    scan.write_bytes(b"changed")
    with pytest.raises(ValueError, match="OPUS file changed"):
        build_handoff(review, str(spectra))
    review.state.pop("spectra_sha256")  # A historical version 1 session may lack hashes.
    assert build_handoff(review, str(spectra)) == handoff

    workbook.write_bytes(b"changed after export")
    with pytest.raises(ValueError, match="cleaned workbook changed"):
        handoff.verify_workbook()

    review.revision += 1
    with pytest.raises(ValueError, match="Export the current"):
        build_handoff(review, str(spectra))
