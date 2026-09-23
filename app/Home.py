from __future__ import annotations

import streamlit as st


st.set_page_config(
    page_title="Soil MIR PLSR",
    page_icon="🌱",
    layout="wide",
)

st.title("Soil MIR PLSR")
st.caption(
    "Local-first MIR calibration, nested validation, model export, and prediction"
)

st.info(
    "The scientific core is migrated behind regression tests. "
    "Full research spectra stay on this computer; GitLab CI uses small test fixtures."
)

st.subheader("Workflow")
cols = st.columns(6)
steps = [
    ("1", "Data", "Inspect spectra, references, and choose a results folder"),
    ("2", "Configure", "Choose properties, model search, and validation settings"),
    ("3", "Run", "Run nested validation with cached OPUS parsing and progress"),
    ("4", "Results", "Review outer-validation metrics and final model choices"),
    ("5", "Predict", "Apply a saved final model to new OPUS spectra"),
    ("6", "History", "Reopen saved run summaries and artifacts"),
]
for col, (number, title, description) in zip(cols, steps):
    with col:
        st.metric(
            f"Step {number}",
            title,
        )
        st.caption(description)

st.subheader("Local-first design")
st.write(
    "Raw OPUS spectra and laboratory reference data stay on your computer. "
    "Parsed OPUS spectra are cached locally using file signatures so repeated STC/STN "
    "runs do not need to re-read unchanged binary files. Each run writes a manifest, "
    "Excel results, resolved settings, split information, and a reusable final model."
)
