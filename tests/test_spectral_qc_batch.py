from io import BytesIO

import numpy as np
import pandas as pd

from soil_mir.qc import Criteria
from soil_mir.services import spectral_qc


def test_standalone_batch_threshold_and_report(tmp_path, monkeypatch):
    names = [f"NSSH_02_{i}_A{i+6}.0" for i in range(1, 4)]
    for name in names + ["unknown.0"]:
        (tmp_path / name).write_bytes(b"fixture")
    axis = np.linspace(600., 4000., 341)
    x = 1 + np.sin(axis / 100.)
    raw = {
        names[0]: (x, axis), names[1]: (x.copy(), axis),
        names[2]: (x + .11 * np.cos(axis / 100.), axis),
        "unknown.0": (x, axis),
    }
    calls = []

    def read(directory, files, cache_root, **kwargs):
        calls.append(files)
        return raw, None

    monkeypatch.setattr(spectral_qc, "load_opus_spectra_cached", read)
    batch = spectral_qc.prepare_batch(tmp_path)
    result = spectral_qc.evaluate_batch(batch, Criteria())
    sample = result["Sample QC"].iloc[0]
    assert sample["Suspected File"] == names[2]
    assert sample["Sample QC"] == "Review"
    relaxed = spectral_qc.evaluate_batch(batch, Criteria(similarity=99.3))
    assert relaxed["Sample QC"].iloc[0]["Sample QC"] == "Pass"
    assert relaxed["Rescan List"].empty
    assert len(calls) == 1
    workbook = pd.ExcelFile(BytesIO(spectral_qc.report_bytes(result)))
    assert set(workbook.sheet_names) == set(result)
    files = pd.read_excel(workbook, "Replicate Diagnosis")
    assert set(files["File Name"]) == set(names + ["unknown.0"])
    assert files.loc[files["File Name"] == names[2], "File Diagnosis"].item() == "Suspected"


def test_bad_file_does_not_abort_batch(tmp_path, monkeypatch):
    names = [f"NSSH_1_{i}_A{i}.0" for i in range(1, 4)]
    for name in names:
        (tmp_path / name).touch()
    axis = np.linspace(600, 4000, 341)

    def bad_cache(*args, **kwargs):
        raise ValueError("unreadable")

    def read(path, **kwargs):
        if path.name == names[2]:
            raise ValueError("unreadable")
        return np.sin(axis / 100), axis

    monkeypatch.setattr(spectral_qc, "load_opus_spectra_cached", bad_cache)
    monkeypatch.setattr(spectral_qc, "read_opus_spectrum", read)
    batch = spectral_qc.prepare_batch(tmp_path)
    result = spectral_qc.evaluate_batch(batch, Criteria())
    assert result["Sample QC"].iloc[0]["Sample QC"] == "Incomplete"
    assert not result["Sample QC"].iloc[0]["Suspected File"]
    assert names[2] in batch.errors
    assert result["File QC"].loc[
        result["File QC"]["File Name"] == names[2], "File Diagnosis"
    ].item() == "Invalid"
