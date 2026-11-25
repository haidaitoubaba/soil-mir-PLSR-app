from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from test_model_catalog import create_run
from soil_mir.services.model_catalog import list_model_catalog


PAGES = Path(__file__).resolve().parents[1] / "app" / "pages"


def _widget(items, label):
    return next(item for item in items if item.label == label)


def test_predict_catalog_never_applies_implicit_model(tmp_path):
    create_run(tmp_path, "a", "TC")
    create_run(tmp_path, "b", "TN")
    app = AppTest.from_file(PAGES / "5_Predict.py", default_timeout=30)
    app.session_state["soil_mir_output_dir"] = str(tmp_path)
    app.run()
    assert not app.exception
    _widget(app.selectbox, "Calibration run").set_value("a").run()
    assert not app.exception
    _widget(app.selectbox, "Soil property").set_value("TC").run()
    _widget(app.selectbox, "Validation method").set_value("kfold").run()
    entry = next(item for item in list_model_catalog(tmp_path) if item["run_id"] == "a")
    _widget(app.selectbox, "Model variant").set_value(entry["id"]).run()
    assert not app.exception
    assert not app.session_state["soil_mir_predict_model_input"]
    _widget(app.button, "Preview selected model").click().run()
    _widget(app.button, "Use selected saved model").click().run()
    assert not app.exception
    assert app.session_state["soil_mir_predict_model_input"] == entry["path"]
    _widget(app.selectbox, "Calibration run").set_value("b").run()
    assert not app.exception
    assert not app.session_state["soil_mir_predict_model_input"]
    assert "TC" not in _widget(app.selectbox, "Soil property").options


def test_results_overview_metrics_follow_selected_property(tmp_path):
    def result(prop, score):
        return {
            "property": prop, "method": "kfold",
            "summary": pd.DataFrame({
                "Metric": ["R2", "RMSE", "RPIQ", "Bias"],
                "Value": [score, 1., 2., 0.],
            }),
            "final_settings": {"Preprocessing": "Raw", "Region": "Full", "Rank": 2},
            "unique_validation_samples": 20, "elapsed_seconds": 1.,
        }
    app = AppTest.from_file(PAGES / "4_Results.py", default_timeout=30)
    app.session_state["soil_mir_results"] = {
        "TC::kfold": result("TC", .8), "TN::kfold": result("TN", .5)
    }
    app.session_state["soil_mir_last_run_dir"] = str(tmp_path)
    app.run()
    assert not app.exception
    assert _widget(app.metric, "R²").value == "0.800"
    _widget(app.selectbox, "Soil property").set_value("TN").run()
    assert not app.exception
    assert _widget(app.metric, "R²").value == "0.500"
