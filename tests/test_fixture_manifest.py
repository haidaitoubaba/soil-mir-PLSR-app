from pathlib import Path

import pandas as pd


FIXTURE = Path(__file__).parent / "fixtures" / "soil_mir_202"


def test_manifest_represents_24_samples_and_12_groups():
    frame = pd.read_csv(FIXTURE / "manifest.csv")
    assert len(frame) == 24
    assert frame["Sample"].nunique() == 24
    assert frame["Group"].nunique() == 12
    assert frame.groupby("Group").size().eq(2).all()
    assert (frame["STC"] > 0).all()
    assert (frame["STN"] > 0).all()
