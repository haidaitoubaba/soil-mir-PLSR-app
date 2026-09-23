from pathlib import Path

import numpy as np

from soil_mir.io.opus import inspect_opus_directory, read_opus_spectrum


FIXTURE = Path(__file__).parent / "fixtures" / "soil_mir_202" / "opus_smoke"


def test_opus_smoke_fixture_has_three_replicates():
    summary = inspect_opus_directory(FIXTURE)
    assert summary.file_count == 3
    assert len(summary.filenames) == 3


def test_real_opus_file_can_be_parsed():
    summary = inspect_opus_directory(FIXTURE)
    absorbance, wavenumbers = read_opus_spectrum(FIXTURE / summary.filenames[0])
    assert absorbance.ndim == 1
    assert wavenumbers.ndim == 1
    assert len(absorbance) == len(wavenumbers)
    assert len(absorbance) > 1000
    assert np.isfinite(absorbance).all()
    assert np.isfinite(wavenumbers).all()
