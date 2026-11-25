import json

import joblib
import numpy as np
import pytest

from soil_mir.reporting import initialize_run_manifest
from soil_mir.services.model_catalog import catalog_options, list_model_catalog, preview_model
from soil_mir.services.run_alias import read_run_alias, set_run_alias


def create_run(root, name, prop):
    path = root / name
    path.mkdir()
    manifest = initialize_run_manifest(
        path, properties=[prop], methods=["kfold"], spectra_dir="/data/s",
        reference_excel="/data/ref.xlsx",
    )
    model = path / "model.joblib"
    joblib.dump({
        "preprocessing_state": {}, "pls_model": object(), "wavenumbers": np.array([600., 602.]),
        "response_transform": "none", "response_transform_parameter": None,
        "property_name": prop, "validation_method": "kfold", "selected_rank": 4,
    }, model)
    record = {
        "property": prop, "method": "kfold", "metrics": {"R2": 0.8},
        "artifacts": {"model": str(model)}, "validation_samples": 20,
    }
    manifest["results"] = [record]
    (path / "Run_Manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def test_alias_does_not_change_manifest_or_model(tmp_path):
    run, _ = create_run(tmp_path, "run1", "TC")
    original = (run / "Run_Manifest.json").read_bytes()
    model = (run / "model.joblib").read_bytes()
    assert set_run_alias(tmp_path, run, "NSSH — 全部") == "NSSH — 全部"
    assert read_run_alias(run) == "NSSH — 全部"
    assert (run / "Run_Manifest.json").read_bytes() == original
    assert (run / "model.joblib").read_bytes() == model
    with pytest.raises(ValueError):
        set_run_alias(tmp_path, run, "a\nb")
    with pytest.raises(ValueError):
        set_run_alias(tmp_path.parent, run, "wrong root")
    assert set_run_alias(tmp_path, run, " ") == ""
    assert read_run_alias(run) == ""


def test_catalog_exact_combinations_and_source_validation_metrics(tmp_path):
    a, manifest = create_run(tmp_path, "a", "TC")
    b, _ = create_run(tmp_path, "b", "TN")
    set_run_alias(tmp_path, a, "same")
    set_run_alias(tmp_path, b, "same")
    refit = a / "refit.joblib"
    joblib.dump({
        "preprocessing_state": {}, "pls_model": object(), "wavenumbers": np.array([600., 602.]),
        "response_transform": "none", "response_transform_parameter": None,
        "property_name": "TC", "validation_method": "kfold", "selected_rank": 2,
        "artifact_role": "final_only_refit",
    }, refit)
    manifest["final_refits"] = [{
        "property": "TC", "method": "kfold", "refit_tolerance_pct": 4,
        "artifacts": {"model": str(refit)},
    }]
    (a / "Run_Manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    catalog = list_model_catalog(tmp_path)
    assert len(catalog) == 3
    assert len({item["id"] for item in catalog}) == 3
    assert not catalog_options(catalog, "a", "TN")
    assert len(catalog_options(catalog, "b", "TN", "kfold")) == 1
    selected = next(item for item in catalog if item["model_role"] == "final_only_refit")
    info = preview_model(selected["path"], selected)
    assert info["fields"]["PLS rank"] == 2
    assert info["fields"]["Spectral points"] == 2
    assert info["metrics"]["R2"] == 0.8
    assert info["metrics"]["RPD"] == "Not recorded"
    assert info["source_only"] is True
