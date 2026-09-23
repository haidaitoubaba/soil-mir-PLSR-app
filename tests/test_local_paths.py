from pathlib import Path

from soil_mir.services.local_paths import (
    detect_local_data_layout,
)


def _make_layout(data_dir: Path):
    spectra = data_dir / "spectra" / "Complete"
    reference = data_dir / "reference"
    spectra.mkdir(parents=True)
    reference.mkdir(parents=True)
    (
        reference
        / "reference_value_ZL_trt.xlsx"
    ).write_bytes(b"placeholder")


def test_environment_data_dir_takes_precedence(tmp_path):
    configured = tmp_path / "configured"
    project = tmp_path / "project"
    _make_layout(configured)
    _make_layout(project / "data")

    layout = detect_local_data_layout(
        home=tmp_path / "home",
        cwd=project,
        environ={
            "SOIL_MIR_DATA_DIR": str(configured)
        },
    )

    assert layout is not None
    assert layout.data_dir == configured
    assert layout.source == "SOIL_MIR_DATA_DIR"


def test_detects_legacy_downloads_layout(tmp_path):
    home = tmp_path / "home"
    data_dir = (
        home
        / "Downloads"
        / "Python Code for Zheya"
        / "Python code for MIR"
        / "data"
    )
    _make_layout(data_dir)

    layout = detect_local_data_layout(
        home=home,
        cwd=tmp_path / "other",
        environ={},
    )

    assert layout is not None
    assert layout.data_dir == data_dir
    assert (
        layout.reference_excel.name
        == "reference_value_ZL_trt.xlsx"
    )
    assert (
        layout.spectra_dir
        == data_dir / "spectra" / "Complete"
    )


def test_returns_none_when_layout_is_missing(tmp_path):
    layout = detect_local_data_layout(
        home=tmp_path / "home",
        cwd=tmp_path / "project",
        environ={},
    )
    assert layout is None
