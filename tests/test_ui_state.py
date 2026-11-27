from streamlit.testing.v1 import AppTest

from soil_mir.ui_state import SECTIONS, valid_choice
from soil_mir.ui_navigation import ICONS, PAGES, section_key


def test_rc6_navigation_inventory():
    section_pages = [name for name in SECTIONS if name not in {"data", "qc"}]
    assert [p[0] for p in PAGES] == ["home", "qc", "cleanup", "data", *section_pages]
    assert PAGES[3][1] == "Modeling Data"
    assert all(s in ICONS for sections in SECTIONS.values() for s in sections)
    assert len(SECTIONS) == 7
    assert sum(map(len, SECTIONS.values())) == 31
    assert all(len(set(sections)) == len(sections) for sections in SECTIONS.values())


def test_choice_resolves_missing_option():
    assert valid_choice("TN", ["TC", "TN"]) == "TN"
    assert valid_choice("missing", ["TC", "TN"], "TN") == "TN"
    assert valid_choice("missing", ["TC"]) == "TC"
    assert valid_choice("missing", []) is None


def test_navigation_and_value_survive_hidden_widget():
    app = AppTest.from_string("""
import streamlit as st
from soil_mir.ui_state import section_navigation, remember_widget
section = section_navigation("data")
if section == "Input Data":
    remember_widget(st, "text_input", "Directory", key="directory")
else:
    st.write(section)
""")
    app.run()
    assert not app.exception
    app.text_input[0].set_value("/example/spectra").run()
    app.button(key=section_key("data", "Data Overview")).click().run()
    assert len(app.text_input) == 0
    app.button(key=section_key("data", "Input Data")).click().run()
    assert not app.exception
    assert app.text_input[0].value == "/example/spectra"


def test_requested_section_is_applied_on_next_rerun():
    app = AppTest.from_string("""
import streamlit as st
from soil_mir.ui_state import section_navigation, request_section
section = section_navigation("qc")
if st.button("Run QC"):
    request_section("qc", "Overview")
    st.rerun()
""")
    app.run()
    next(b for b in app.button if b.label == "Run QC").click().run()
    assert not app.exception
    assert app.session_state["rc6_section_qc"] == "Overview"
