from pathlib import Path

import pandas as pd


FIXTURE = Path(__file__).parent / "fixtures" / "soil_mir_202"


def test_lightweight_model_matrix_represents_24_samples_and_12_groups():
    frame = pd.read_csv(FIXTURE / "model_matrix.csv")
    spectral_cols = [name for name in frame.columns if name.startswith("wn_")]
    assert len(frame) == 24
    assert frame["Sample"].nunique() == 24
    assert frame["Group"].nunique() == 12
    assert len(spectral_cols) == 256
    assert frame[spectral_cols].notna().all().all()
    assert (frame["STC"] > 0).all()
    assert (frame["STN"] > 0).all()
