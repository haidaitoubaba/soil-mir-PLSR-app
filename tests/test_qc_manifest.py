from io import BytesIO

import numpy as np
import pandas as pd
import pytest

from soil_mir.config import ColumnConfig
from soil_mir.qc import Criteria
from soil_mir.services import spectral_qc
from soil_mir.services.qc_manifest import (
    build_manifest, filter_reference, read_manifest, read_mapping, resolve_groups,
    save_manifest, validate_manifest,
)


def test_mapping_and_frozen_selection(tmp_path, monkeypatch):
    names = ["a.0", "b.1", "c.0"]
    mapping = read_mapping(BytesIO(
        b"File Name,Sample,Replicate\n"
        b"a.0,001,1\nb.1,001,2\nc.0,001,3\n"
    ))
    groups, unmatched, detected = resolve_groups(names, "Auto", mapping)
    assert list(groups) == ["001"] and not unmatched and detected == "Explicit mapping"
    for name in names:
        (tmp_path / name).write_bytes(name.encode())
    axis = np.linspace(600, 4000, 341)
    x = np.sin(axis / 100)
    raw = {names[0]: (x, axis), names[1]: (x, axis), names[2]: (-x, axis)}
    monkeypatch.setattr(
        spectral_qc, "load_opus_spectra_cached", lambda *args, **kwargs: (raw, None)
    )
    batch = spectral_qc.prepare_batch(tmp_path, mapping=mapping)
    criteria = Criteria()
    tables = spectral_qc.evaluate_batch(batch, criteria)
    with pytest.raises(ValueError, match="unresolved"):
        build_manifest(batch, criteria, tables, {}, freeze=True)
    decisions = {
        name: {"decision": "Keep" if name != names[2] else "Exclude", "reason": "review"}
        for name in names
    }
    payload = build_manifest(batch, criteria, tables, decisions, freeze=True)
    path = save_manifest(tmp_path / "QC_Manifest.json", payload)
    restored = read_manifest(path)
    validate_manifest(restored, tmp_path, frozen=True)
    assert restored["selection"]["retained"] == names[:2]
    columns = ColumnConfig()
    frame = pd.DataFrame({
        columns.reference_file: names,
        columns.sample_id: ["001"] * 3,
        columns.reference_value: [3.] * 3,
    })
    filtered, excluded = filter_reference(frame, columns, restored)
    assert len(filtered) == 2 and excluded == 1
    frame.loc[0, columns.sample_id] = "different"
    with pytest.raises(ValueError, match="conflicts"):
        filter_reference(frame, columns, restored)
    (tmp_path / names[0]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="content changed"):
        validate_manifest(restored, tmp_path, frozen=True)


def test_mapping_missing_id_and_multiple_batches():
    mapping = read_mapping(BytesIO(b"File Name,Sample\na.0,001\n"))
    groups, _, _ = resolve_groups(["a.0"], "Auto", mapping)
    assert groups["001"][0].replicate == 0
    with pytest.raises(ValueError, match="multiple Batch"):
        read_mapping(BytesIO(b"File Name,Sample,Batch\na.0,001,L1\nb.0,001,L2\n"))
    with pytest.raises(ValueError, match="absent"):
        resolve_groups(["b.0"], "Auto", mapping)



def test_qc_filter_calibration_integration(tmp_path, monkeypatch):
    from soil_mir.io.cache import OpusCacheStats
    from soil_mir.services import calibration

    folder = tmp_path / "spectra"
    folder.mkdir()
    names = [f"S1_{i}.0" for i in (1, 2, 3)]
    for name in names:
        (folder / name).write_bytes(name.encode())
    axis = np.linspace(600, 4000, 341)
    x = np.sin(axis / 100)
    raw = {name: (x if i < 2 else -x, axis) for i, name in enumerate(names)}
    monkeypatch.setattr(
        spectral_qc, "load_opus_spectra_cached", lambda *args, **kwargs: (raw, None)
    )
    batch = spectral_qc.prepare_batch(folder)
    criteria = Criteria()
    decisions = {name: {"decision": "Keep" if i < 2 else "Exclude", "reason": "checked"}
                 for i, name in enumerate(names)}
    payload = build_manifest(batch, criteria, spectral_qc.evaluate_batch(batch, criteria),
                             decisions, freeze=True)
    workbook = tmp_path / "reference.xlsx"
    pd.DataFrame({"Sample": ["S1"] * 3, "Reference Value": [3.] * 3, "File Name": names,
                  "Group": ["A"] * 3}).to_excel(workbook, sheet_name="STC", index=False)
    requested = []

    def cache(directory, filenames, cache_root=None, **kwargs):
        requested.extend(filenames)
        return ({n: raw[n] for n in filenames},
                OpusCacheStats(0, len(filenames), len(filenames), None))

    monkeypatch.setattr(calibration, "load_opus_spectra_cached", cache)
    dataset = calibration.load_calibration_dataset(
        folder, workbook, "STC", 600., 4000., False, qc_manifest=payload
    )
    assert requested == names[:2]
    assert dataset.rows == 2 and dataset.unique_samples == 1
    assert set(dataset.sample_ids) == {"S1"}
    assert dataset.qc_manifest_id == payload["manifest_id"]
    assert dataset.excluded_qc_rows == 1
    assert len(list(folder.iterdir())) == 3


def test_manifest_detects_same_size_edit_before_freeze(tmp_path, monkeypatch):
    import os

    names = [f"S1_{i}.0" for i in (1, 2, 3)]
    for name in names:
        (tmp_path / name).write_bytes(b"aaaa")
    axis = np.linspace(600, 4000, 341)
    x = np.sin(axis / 100)
    raw = {name: (x, axis) for name in names}
    monkeypatch.setattr(
        spectral_qc, "load_opus_spectra_cached", lambda *args, **kwargs: (raw, None)
    )
    batch = spectral_qc.prepare_batch(tmp_path)
    criteria = Criteria()
    path = tmp_path / names[0]
    stat = path.stat()
    path.write_bytes(b"bbbb")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ValueError, match="content changed since QC"):
        build_manifest(batch, criteria, spectral_qc.evaluate_batch(batch, criteria), {})
