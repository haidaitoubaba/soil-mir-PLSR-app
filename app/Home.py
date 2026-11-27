from __future__ import annotations

import streamlit as st

from soil_mir.ui_navigation import render_sidebar


st.set_page_config(
    page_title="Soil MIR PLSR", page_icon=":material/eco:", layout="wide",
    initial_sidebar_state="expanded",
)


def render_home():
    st.title("Soil MIR PLSR")
    st.caption(
        "Local-first MIR calibration, nested validation, model export, and prediction"
    )

    st.info(
        "The scientific core is migrated behind regression tests. "
        "Full research spectra stay on this computer; GitLab CI uses small test fixtures."
    )

    st.subheader("Standalone spectral quality control")
    st.page_link("pages/1_Spectral_QC.py", label="Spectral QC", icon=":material/document_scanner:")
    st.caption("Compare replicate OPUS spectra without reference values or model training.")

    st.subheader("Calibration")
    cleanup, modeling_data = st.columns(2)
    with cleanup:
        st.page_link("pages/1_Cleanup.py", label="Cleanup", icon=":material/cleaning_services:")
        st.caption("Review spectra and reference values before calibration.")
    with modeling_data:
        st.page_link("pages/1_Data.py", label="Modeling Data", icon=":material/database:")
        st.caption("Open an existing OPUS folder and reference workbook for modeling.")

    st.caption("After inspecting the modeling data, open Configuration, Run, and Results.")

    st.subheader("Local-first design")
    st.write(
        "Raw OPUS spectra and laboratory reference data stay on your computer. "
        "Parsed OPUS spectra are cached locally using file signatures so repeated STC/STN "
        "runs do not need to re-read unchanged binary files. Each run writes a manifest, "
        "Excel results, resolved settings, split information, and a reusable final model."
    )


render_sidebar(render_home).run()
