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



def test_auto_shared_range_accepts_native_opus_endpoints(tmp_path, monkeypatch):
    names = [f"NSSH_{s}_{r}_A{s*3+r}.0" for s in (1, 2) for r in (1, 2, 3)]
    for name in names:
        (tmp_path / name).touch()
    axis1 = np.linspace(649.8, 3999.8, 1676)
    axis2 = np.linspace(650.2, 3999.5, 1676)
    raw = {
        name: (np.sin(axis / 100), axis)
        for i, name in enumerate(names)
        for axis in [axis1 if i < 3 else axis2]
    }
    monkeypatch.setattr(
        spectral_qc, "load_opus_spectra_cached", lambda *args, **kwargs: (raw, None)
    )
    batch = spectral_qc.prepare_batch(tmp_path)
    assert batch.effective_lower == 650.2
    assert batch.effective_upper == 3999.5
    assert not batch.errors
    tables = spectral_qc.evaluate_batch(batch, Criteria())
    assert tables["Sample QC"]["Sample QC"].tolist() == ["Pass", "Pass"]
    for axis, _ in batch.aligned.values():
        assert axis.min() >= batch.effective_lower
        assert axis.max() <= batch.effective_upper
    settings = tables["Settings"].set_index("Field")["Value"]
    assert settings["Effective minimum (cm⁻¹)"] == 650.2
    strict = spectral_qc.prepare_batch(tmp_path, range_mode="manual")
    result = spectral_qc.evaluate_batch(strict, Criteria())
    assert result["Sample QC"]["Sample QC"].tolist() == ["Incomplete", "Incomplete"]
    overview = result["Overview"].set_index("Metric")["Value"]
    assert overview["Read errors"] == 0
    assert overview["Input validation errors"] == 6
    assert overview["Evaluable samples"] == 0
    assert pd.isna(overview["Sample pass rate (%)"])
    assert "649.8000" in result["File QC"].iloc[0]["Input validation error"]


def test_auto_range_ignores_unmatched_and_unreadable(tmp_path, monkeypatch):
    names = [f"NSSH_1_{i}_A{i}.0" for i in range(1, 4)]
    for name in names + ["unknown.0"]:
        (tmp_path / name).touch()
    axis = np.linspace(600, 4000, 341)
    narrow = np.linspace(1000, 2000, 101)
    raw = {name: (np.sin(axis/100), axis) for name in names}
    raw["unknown.0"] = (np.sin(narrow/100), narrow)
    monkeypatch.setattr(
        spectral_qc, "load_opus_spectra_cached", lambda *args, **kwargs: (raw, None)
    )
    batch = spectral_qc.prepare_batch(tmp_path)
    assert batch.effective_lower == 600
    assert batch.effective_upper == 4000
    assert spectral_qc.evaluate_batch(batch, Criteria())["Sample QC"].iloc[0]["Sample QC"] == "Pass"



def test_auto_range_reads_actual_opus_metadata_without_nominal_limits(tmp_path, monkeypatch):
    import brukeropusreader

    names = [f"NSSH_1_{i}_A{i}.0" for i in (1, 2, 3)]
    for name in names:
        (tmp_path / name).touch()
    axis = np.linspace(4001.5, 399.5, 1802)
    # AB storage is padded; NPT, FXV and LXV define the measured coordinates.
    data = {
        "AB": np.append(1 + np.sin(axis / 100), [999., 999.]),
        "AB Data Parameter": {"NPT": len(axis), "FXV": axis[0], "LXV": axis[-1], "CSF": 1.},
    }
    monkeypatch.setattr(brukeropusreader, "read_file", lambda _: data)
    batch = spectral_qc.prepare_batch(tmp_path)
    assert batch.lower is None and batch.upper is None
    assert batch.effective_lower == 399.5
    assert batch.effective_upper == 4001.5
    assert batch.native_range_count == 1
    assert batch.native_envelope_lower == 399.5
    assert batch.native_envelope_upper == 4001.5
    for _, native_axis in batch.raw.values():
        assert len(native_axis) == len(axis)
    tables = spectral_qc.evaluate_batch(batch, Criteria())
    assert tables["Sample QC"]["Sample QC"].tolist() == ["Pass"]
    assert tables["Pairwise QC"]["Points"].tolist() == [len(axis)] * 3
    strict = spectral_qc.prepare_batch(tmp_path, range_mode="manual")
    assert strict.effective_lower == 600
    assert strict.effective_upper == 4000



def test_agreed_export_and_apply_recommendations(tmp_path, monkeypatch):
    names = [f"NSSH_{s}_{i}_A{i}.0" for s in (1, 2, 3) for i in (1, 2, 3)]
    for name in names:
        (tmp_path / name).touch()
    axis = np.linspace(400, 4000, 361)
    x = 1 + np.sin(axis / 100)
    noise = np.cos(axis / 100)
    raw = {}
    for name, values in zip(names, [x, x, x, x, x, x + .2*noise,
                                    x, x + .05*noise, x - .05*noise]):
        raw[name] = (values, axis)
    monkeypatch.setattr(
        spectral_qc, "load_opus_spectra_cached", lambda *args, **kwargs: (raw, None)
    )
    batch = spectral_qc.prepare_batch(tmp_path)
    criteria = Criteria()
    tables = spectral_qc.evaluate_batch(batch, criteria)
    assert set(tables["Agreed Spectra"]["File Name"]) == set(names[:5])
    assert tables["Sample QC"]["Sample QC"].tolist() == ["Pass", "Review", "Review"]
    prior = {names[0]: {"decision": "Exclude", "reason": "manual"}}
    updated = spectral_qc.recommended_reviews(tables, prior)
    assert updated[names[0]] == prior[names[0]]
    assert updated[names[3]]["decision"] == "Keep"
    assert updated[names[5]]["decision"] == "Rescan required"
    assert updated[names[5]]["source"] == "Applied recommendation"
    assert not any(name in updated for name in names[6:])
    assert len(spectral_qc.recommended_reviews(tables, updated)) == len(updated)


def test_preview_is_not_qc_preprocessing(tmp_path, monkeypatch):
    names = [f"NSSH_1_{i}_A{i}.0" for i in (1, 2, 3)]
    for name in names:
        (tmp_path / name).touch()
    axis = np.linspace(400, 4000, 361)
    x = 1 + np.sin(axis / 100)
    raw = {name: (x * (i + 1) + i, axis) for i, name in enumerate(names)}
    monkeypatch.setattr(
        spectral_qc, "load_opus_spectra_cached", lambda *args, **kwargs: (raw, None)
    )
    batch = spectral_qc.prepare_batch(tmp_path)
    before = spectral_qc.evaluate_batch(batch, Criteria())["Pairwise QC"]
    out_axis, processed = spectral_qc.preview_spectra(batch, "NSSH_1", "SNV")
    assert out_axis[0] > out_axis[-1]
    np.testing.assert_allclose(processed[names[0]], processed[names[2]], atol=1e-10)
    _, smooth = spectral_qc.preview_spectra(batch, "NSSH_1", "SG Smoothing", 11, 2)
    assert not np.array_equal(smooth[names[0]], x[::-1])
    after = spectral_qc.evaluate_batch(batch, Criteria())["Pairwise QC"]
    pd.testing.assert_frame_equal(before, after)



def test_dual_evaluation_uses_cached_pearson_and_reference_id(tmp_path, monkeypatch):
    names = [f"NSSH_{s}_{i}_A{i}.0" for s in (1, 2, 3) for i in (1, 2, 3)]
    for name in names:
        (tmp_path / name).touch()
    axis = np.linspace(400, 4000, 361)
    x = 1 + np.sin(axis / 100)
    noise = np.cos(axis / 100)
    values = [x, x, x, x + .2*noise, x, x, x, x + .05*noise, x - .05*noise]
    raw = {name: (value, axis) for name, value in zip(names, values)}
    calls = []

    def read(*args, **kwargs):
        calls.append(1)
        return raw, None

    monkeypatch.setattr(spectral_qc, "load_opus_spectra_cached", read)
    batch = spectral_qc.prepare_batch(tmp_path)
    tables = spectral_qc.evaluate_batch(batch, Criteria())
    comp = tables["Method Comparison"]
    assert comp["USDA-style status"].tolist() == ["Pass", "Not pass", "Pass"]
    assert comp["All-pairwise Pearson status"].tolist() == ["Pass", "Not pass", "Not pass"]
    assert comp["Method agreement"].tolist() == ["Agree", "Agree", "Disagree"]
    assert comp["Replicate 1 suspected (Pearson)"].tolist() == [False, True, False]
    assert comp["Reference file"].tolist() == names[::3]
    sens = tables["Threshold Sensitivity"].set_index("Threshold (%)")
    assert sens.loc[99.6, "USDA-style pass"] == 2
    assert sens.loc[99.6, "All-pairwise Pearson pass"] == 1
    assert sens.loc[99.6, "USDA pass / all-pair not pass"] == 1
    advanced = spectral_qc.evaluate_batch(batch, Criteria(advanced=True))
    pd.testing.assert_frame_equal(
        comp.drop(columns="Active all-pair QC"),
        advanced["Method Comparison"].drop(columns="Active all-pair QC"),
    )
    assert len(calls) == 1


def test_dual_evaluation_four_replicates_and_missing_reference():
    from itertools import combinations
    from soil_mir.qc import Scan, compare_strategies

    scans = [Scan(f"file_{i}.0", "sample", i) for i in (4, 2, 1, 3)]
    entries = [(a, b, {"r": .998 if 1 in (a.replicate, b.replicate) else .993}, "")
               for a, b in combinations(scans, 2)]
    row = compare_strategies(scans, entries, 99.6, 4)
    assert row["Reference file"] == "file_1.0"
    assert row["USDA-style pairs passed"] == 3
    assert row["All-pairwise expected pairs"] == 6
    assert row["Method agreement"] == "Disagree"
    assert compare_strategies(scans, entries, 99.8, 4)["USDA-style status"] == "Not pass"
    no_reference = [scan for scan in scans if scan.replicate != 1]
    remaining = [entry for entry in entries if 1 not in (entry[0].replicate, entry[1].replicate)]
    missing = compare_strategies(no_reference, remaining, 99.6, 4)
    assert missing["Reference file"] == ""
    assert missing["Method agreement"] == "Not comparable"
