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



def test_optional_reason_and_edit_sync(tmp_path, monkeypatch):
    from soil_mir.services.qc_manifest import apply_review_edits

    names = [f"S1_{i}.0" for i in (1, 2, 3)]
    for name in names:
        (tmp_path / name).write_bytes(name.encode())
    axis = np.linspace(600, 4000, 341)
    x = 1 + np.sin(axis / 100)
    # Opposite centered signals with a positive baseline keep NRMSE defined.
    raw = {name: (x if i < 2 else 2 - x, axis) for i, name in enumerate(names)}
    monkeypatch.setattr(
        spectral_qc, "load_opus_spectra_cached", lambda *args, **kwargs: (raw, None)
    )
    batch = spectral_qc.prepare_batch(tmp_path)
    tables = spectral_qc.evaluate_batch(batch, Criteria())
    edits = [{"File Name": name, "Manual decision": "Keep" if i < 2 else "Exclude"}
             for i, name in enumerate(names)]
    decisions = apply_review_edits(tables["File QC"], {}, edits)
    assert all(d["reason"] == "" and d["source"] == "Manual" for d in decisions.values())
    tables = spectral_qc.evaluate_batch(batch, Criteria(), decisions)
    assert tables["Review decisions"]["Manual decision"].tolist() == ["Keep", "Keep", "Exclude"]
    assert tables["Agreed Spectra"]["Manual decision"].tolist() == ["Keep", "Keep"]
    payload = build_manifest(batch, Criteria(), tables, decisions, freeze=True)
    assert payload["selection"]["retained"] == names[:2]
    changed = apply_review_edits(tables["File QC"], decisions, [
        {"File Name": names[2], "Manual decision": "Rescan required"},
    ])
    assert changed[names[0]] == decisions[names[0]]
    assert changed[names[2]]["decision"] == "Rescan required"
    tables = spectral_qc.evaluate_batch(batch, Criteria(), changed)
    assert "Confirmed rescan" in tables["Rescan List"]["Type"].tolist()


def test_export_decision_spectra_copies_and_verifies(tmp_path, monkeypatch):
    from soil_mir.services.qc_manifest import decision_export_rows, export_decision_spectra

    source = tmp_path / "original"
    source.mkdir()
    names = [f"S1_{i}.0" for i in (1, 2, 3)]
    for name in names:
        (source / name).write_bytes(name.encode())
    axis = np.linspace(600, 4000, 341)
    x = np.sin(axis / 100)
    raw = {name: (x, axis) for name in names}
    monkeypatch.setattr(
        spectral_qc, "load_opus_spectra_cached", lambda *args, **kwargs: (raw, None)
    )
    batch = spectral_qc.prepare_batch(source)
    criteria = Criteria()
    decisions = {names[0]: {"decision": "Keep"}, names[1]: {"decision": "Rescan required"}}
    tables = spectral_qc.evaluate_batch(batch, criteria, decisions)
    assert len(decision_export_rows(tables["File QC"], decisions, ["Keep"])) == 1
    target, count = export_decision_spectra(
        batch, tables, decisions, ["Keep", "Rescan required"], tmp_path / "copy", criteria
    )
    assert count == 2
    assert (target / "Keep" / names[0]).read_bytes() == names[0].encode()
    assert (target / "Rescan_required" / names[1]).read_bytes() == names[1].encode()
    assert not (target / "Keep" / names[2]).exists()
    assert len(list(source.iterdir())) == 3
    assert len(pd.read_csv(target / "Exported_Spectra.csv")) == 2
    assert (target / "Export_Settings.json").is_file()
    with pytest.raises(FileExistsError):
        export_decision_spectra(batch, tables, decisions, ["Keep"], target, criteria)
    with pytest.raises(ValueError, match="outside"):
        export_decision_spectra(batch, tables, decisions, ["Keep"], source / "copy", criteria)
    import os

    file = source / names[0]
    stat = file.stat()
    file.write_bytes(b"x" * stat.st_size)
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ValueError, match="content changed"):
        export_decision_spectra(
            batch, tables, decisions, ["Keep"], tmp_path / "changed", criteria
        )
    assert not (tmp_path / "changed").exists()


def test_invalid_review_keep_rejected():
    from soil_mir.services.qc_manifest import apply_review_edits

    frame = pd.DataFrame({"File Name": ["a.0", "b.0"], "File Diagnosis": ["Invalid", "Unmatched"]})
    for name in ("a.0", "b.0"):
        with pytest.raises(ValueError, match="Cannot Keep"):
            apply_review_edits(frame, {}, [{"File Name": name, "Manual decision": "Keep"}])


def test_review_history_clear_and_undo():
    from soil_mir.services.qc_manifest import review_history_push, review_history_undo

    original = {"a.0": {"decision": "Keep", "reason": "checked", "source": "Manual"}}
    batch = {**original, "b.0": {
        "decision": "Rescan required", "reason": "suspected",
        "source": "Applied recommendation",
    }}
    history = review_history_push(original, batch, [])
    assert review_history_push(batch, batch, history) is history
    history = review_history_push(batch, {}, history)
    restored, history = review_history_undo({}, history)
    assert restored == batch
    restored, history = review_history_undo(restored, history)
    assert restored == original
    assert not history
    restored, history = review_history_undo(restored, history)
    assert restored == original
    assert not history


def test_review_history_is_bounded_and_isolated():
    from soil_mir.services.qc_manifest import review_history_push, review_history_undo

    history = []
    current = {}
    for i in range(25):
        updated = {"a.0": {"decision": "Keep", "reason": str(i)}}
        history = review_history_push(current, updated, history)
        current = updated
    assert len(history) == 20
    restored, remaining = review_history_undo(current, history)
    assert restored["a.0"]["reason"] == "23"
    restored["a.0"]["reason"] = "changed"
    assert history[-1]["a.0"]["reason"] == "23"
    assert len(remaining) == 19


def test_unreviewed_source_and_pending_recommendation(tmp_path, monkeypatch):
    from soil_mir.services.qc_manifest import decision_export_rows

    names = [f"S1_{i}.0" for i in (1, 2, 3)]
    for name in names:
        (tmp_path / name).write_bytes(name.encode())
    axis = np.linspace(600, 4000, 341)
    raw = {name: (2 + np.sin(axis / 100 + i), axis) for i, name in enumerate(names)}
    monkeypatch.setattr(
        spectral_qc, "load_opus_spectra_cached", lambda *args, **kwargs: (raw, None)
    )
    batch = spectral_qc.prepare_batch(tmp_path)
    decisions = {
        name: {"decision": "Pending review", "source": "Manual", "reason": ""}
        for name in names[:2]
    }
    tables = spectral_qc.evaluate_batch(batch, Criteria(), decisions)
    assert spectral_qc.recommended_reviews(tables, decisions) == decisions
    assert tables["Review decisions"]["Decision source"].tolist() == [
        "Manual", "Manual", "Not reviewed",
    ]
    assert [r["Decision source"] for r in decision_export_rows(
        tables["File QC"], decisions, ["Pending review"]
    )] == ["Manual", "Manual", "Not reviewed"]
    assert tables["Pairwise QC"]["Reference comparison"].tolist() == [True, True, False]
