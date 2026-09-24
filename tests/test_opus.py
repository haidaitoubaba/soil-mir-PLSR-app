from pathlib import Path

import brukeropusreader
import numpy as np

from soil_mir.io.opus import (
    align_spectral_library,
    inspect_opus_directory,
)


def test_science_dependency_is_installable():
    assert brukeropusreader is not None


def test_opus_directory_detection_uses_numeric_extensions(tmp_path: Path):
    (tmp_path / "sample_1.0").write_bytes(b"not parsed in this unit test")
    (tmp_path / "sample_1.1").write_bytes(b"not parsed in this unit test")
    (tmp_path / "notes.txt").write_text("ignore me")
    summary = inspect_opus_directory(tmp_path)
    assert summary.file_count == 2
    assert summary.filenames == ("sample_1.0", "sample_1.1")


def test_spectral_alignment_trims_to_shared_coverage_without_extrapolation():
    reference_axis = np.array(
        [4000.0, 3000.0, 2000.0, 1000.0, 0.0]
    )
    slightly_narrower = np.array(
        [3999.0, 2999.0, 1999.0, 999.0, -1.0]
    )
    different_length = np.array(
        [4100.0, 3300.0, 2500.0, 1700.0, 900.0, 100.0]
    )

    raw_axes = {
        "a.0": reference_axis,
        "b.0": slightly_narrower,
        "c.0": different_length,
    }
    raw_spectra = {
        name: axis * 0.001
        for name, axis in raw_axes.items()
    }

    aligned, common_axis = align_spectral_library(
        raw_spectra,
        raw_axes,
    )

    np.testing.assert_array_equal(
        common_axis,
        np.array([3000.0, 2000.0, 1000.0]),
    )
    assert common_axis[0] > common_axis[-1]
    assert set(aligned) == set(raw_spectra)
    assert all(
        values.shape == common_axis.shape
        for values in aligned.values()
    )
    for values in aligned.values():
        np.testing.assert_allclose(
            values,
            common_axis * 0.001,
            rtol=0,
            atol=1e-12,
        )
