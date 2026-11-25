from pathlib import Path

import numpy as np
from streamlit.testing.v1 import AppTest

from soil_mir.services import spectral_qc
from soil_mir.ui_navigation import section_key


PAGE = Path(__file__).resolve().parents[1] / "app" / "pages" / "1_Spectral_QC.py"


def button(app, label):
    return next(w for w in app.button if w.label == label)


def section(app, value):
    app.button(key=section_key("qc", value)).click().run()
    assert not app.exception


def test_qc_sections_keep_batch_review_and_filter(tmp_path, monkeypatch):
    names = [f"S1_{i}.0" for i in (1, 2, 3)]
    for name in names:
        (tmp_path / name).write_bytes(name.encode())
    axis = np.linspace(600, 4000, 341)
    raw = {name: (1 + np.sin(axis / 100), axis) for name in names}
    reads = []
    evaluations = []
    original = spectral_qc.evaluate_batch

    def read(*args, **kwargs):
        reads.append(True)
        return raw, None

    def evaluate(*args, **kwargs):
        evaluations.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(spectral_qc, "load_opus_spectra_cached", read)
    monkeypatch.setattr(spectral_qc, "evaluate_batch", evaluate)
    app = AppTest.from_file(PAGE, default_timeout=30).run()
    assert not app.exception
    app.text_input(key="_rc6_value_qc_dir").set_value(str(tmp_path)).run()
    assert not app.exception
    button(app, "Run QC").click().run()
    assert not app.exception
    assert app.session_state["rc6_section_qc"] == "Overview"
    assert len(reads) == len(evaluations) == 1

    section(app, "Review")
    button(app, "Apply recommended decisions to unreviewed files").click().run()
    assert not app.exception
    assert len(app.session_state["qc_reviews"]) == 3
    assert len(evaluations) == 2
    section(app, "Diagnostics")
    app.radio(key="_rc6_value_qc_comparison_view").set_value("Disagreements").run()
    assert not app.exception
    assert app.session_state["rc6_section_qc"] == "Diagnostics"
    assert len(app.session_state["qc_reviews"]) == 3
    section(app, "Export")
    section(app, "Calibration")
    section(app, "Setup")
    assert app.text_input(key="_rc6_value_qc_dir").value == str(tmp_path)
    section(app, "Diagnostics")
    assert app.radio(key="_rc6_value_qc_comparison_view").value == "Disagreements"
    assert len(reads) == 1
    assert len(evaluations) == 2

    # Source inventory changes invalidate the current QC batch without rereading spectra.
    (tmp_path / names[0]).write_bytes(b"changed")
    section(app, "Export")
    assert any("Input files have changed" in w.value for w in app.warning)
    assert not any(w.label == "Save Excel QC report" for w in app.button)
    assert len(reads) == 1
