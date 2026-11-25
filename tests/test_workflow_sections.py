from pathlib import Path

from streamlit.testing.v1 import AppTest

from soil_mir.services.profiles import save_profile
from soil_mir.ui_navigation import section_key


PAGES = Path(__file__).resolve().parents[1] / "app" / "pages"


def test_configuration_sections_preserve_drafts(tmp_path):
    app = AppTest.from_file(PAGES / "2_Configuration.py", default_timeout=20)
    app.session_state["soil_mir_properties"] = ["TC", "TN"]
    app.session_state["soil_mir_output_dir"] = str(tmp_path)
    app.run()
    assert not app.exception
    app.multiselect(key="_rc6_cfg_cfg_selected_properties").set_value(["TC"]).run()
    app.number_input(key="_rc6_cfg_cfg_wn_min").set_value(650.0).run()
    app.button(key=section_key("configuration", "Validation")).click().run()
    assert not app.exception
    app.number_input(key="_rc6_cfg_cfg_random_seed").set_value(100).run()
    app.button(key=section_key("configuration", "Advanced")).click().run()
    assert not app.exception
    app.text_input(key="_rc6_cfg_ref_min_TC").set_value("0.2").run()
    app.button(key=section_key("configuration", "General")).click().run()
    assert app.multiselect(key="_rc6_cfg_cfg_selected_properties").value == ["TC"]
    assert app.number_input(key="_rc6_cfg_cfg_wn_min").value == 650.0
    next(b for b in app.button if b.label == "Validate and save configuration").click().run()
    assert not app.exception
    assert app.session_state["soil_mir_selected_properties"] == ["TC"]
    assert app.session_state["soil_mir_random_seed"] == 100
    assert app.session_state["soil_mir_reference_ranges"]["TC"]["min"] == 0.2
    assert not app.session_state["rc6_configuration_dirty"]


def test_profile_load_updates_inactive_configuration_sections(tmp_path):
    save_profile(tmp_path, "test", {
        "soil_mir_selected_properties": ["TN"],
        "soil_mir_wn_range": (700.0, 3900.0),
        "soil_mir_random_seed": 100,
        "soil_mir_reference_ranges": {"TN": {"min": 0.5, "max": 10.0}},
    })
    app = AppTest.from_file(PAGES / "2_Configuration.py", default_timeout=20)
    app.session_state["soil_mir_properties"] = ["TC", "TN"]
    app.session_state["soil_mir_output_dir"] = str(tmp_path)
    app.run()
    app.button(key=section_key("configuration", "Profiles")).click().run()
    next(b for b in app.button if b.label == "Load selected profile").click().run()
    assert not app.exception
    app.button(key=section_key("configuration", "General")).click().run()
    assert app.multiselect(key="_rc6_cfg_cfg_selected_properties").value == ["TN"]
    assert app.number_input(key="_rc6_cfg_cfg_wn_min").value == 700.0
    app.button(key=section_key("configuration", "Validation")).click().run()
    assert app.number_input(key="_rc6_cfg_cfg_random_seed").value == 100
    app.button(key=section_key("configuration", "Advanced")).click().run()
    assert app.text_input(key="_rc6_cfg_ref_min_TN").value == "0.5"


def test_run_summary_accessible_without_current_configuration():
    app = AppTest.from_file(PAGES / "3_Run.py", default_timeout=20)
    app.session_state["soil_mir_last_run_outcome"] = {
        "status": "completed", "message": "Finished", "run_dir": "/example/results"
    }
    app.run()
    app.button(key=section_key("run", "Summary")).click().run()
    assert not app.exception
    assert any("Finished" in w.value for w in app.success)
