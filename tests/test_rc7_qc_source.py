from soil_mir.ui_qc_source import (
    applied_directory, choose_source, completed_batch, effective_directory,
    guard_source, record_data_inspection, source_mode,
)


def batch(path):
    return {"qc_config": (str(path), ()), "qc_data": object(),
            "qc_reviews": {"sample": "Keep"}, "qc_frozen": "/saved/manifest.json",
            "soil_mir_qc_manifest_path": "/explicit/manual.json"}


def test_data_only_publishes_successful_inspection(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    state = {"rc6_data_draft": (str(a), "", "")}
    assert source_mode(state) == "independent"
    assert not applied_directory(state)
    record_data_inspection(state, a)
    assert source_mode(state) == "linked"
    assert effective_directory(state) == str(a)
    state["rc6_data_draft"] = (str(b), "", "")
    assert effective_directory(state) == str(a)
    assert not state.get("qc_data")


def test_linked_change_blocks_old_batch_and_preserves_disk_manifest(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    manifest = tmp_path / "saved.json"
    manifest.write_text("original")
    state = batch(a)
    state["qc_frozen"] = str(manifest)
    record_data_inspection(state, a)
    assert not guard_source(state, a)
    record_data_inspection(state, b)
    assert guard_source(state, b)
    assert "qc_frozen" not in state
    assert state["soil_mir_qc_manifest_path"] == "/explicit/manual.json"
    assert manifest.read_text() == "original"
    assert state["qc_reviews"] == {"sample": "Keep"}
    record_data_inspection(state, a)
    assert guard_source(state, a)  # A -> B -> A is not silent reactivation.
    completed_batch(state)
    assert not guard_source(state, a)


def test_independent_ignores_data_and_same_source_preserves_review(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    state = batch(a)
    state["rc6_value_qc_dir"] = str(a)
    choose_source(state, "independent")
    record_data_inspection(state, b)
    assert effective_directory(state) == str(a)
    assert not guard_source(state, a)
    assert "qc_frozen" in state
    record_data_inspection(state, a)
    choose_source(state, "linked")
    assert not guard_source(state, a)
    assert "qc_frozen" in state
    choose_source(state, "independent")
    assert state["rc6_value_qc_dir"] == str(a)
    assert effective_directory(state) == str(a)


def test_explicit_independent_without_data_stays_independent(tmp_path):
    state = {}
    choose_source(state, "independent")
    record_data_inspection(state, tmp_path)
    assert source_mode(state) == "independent"
    assert not effective_directory(state)


def test_missing_link_never_falls_back_to_independent(tmp_path):
    state = {"rc6_value_qc_dir": str(tmp_path)}
    choose_source(state, "linked")
    assert not effective_directory(state)
    record_data_inspection(state, tmp_path / "missing")
    assert effective_directory(state) == str(tmp_path / "missing")
