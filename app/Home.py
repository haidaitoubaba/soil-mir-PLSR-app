from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Soil MIR PLSR", page_icon="🌱", layout="wide")

st.title("Soil MIR PLSR")
st.caption("Local-first MIR calibration, validation, and prediction")

st.info(
    "M1 foundation: inspect local OPUS spectra and the reference workbook before any model run. "
    "The scientific modelling engine will be migrated behind regression tests in later milestones."
)

st.subheader("Workflow")
cols = st.columns(5)
steps = [
    ("1", "Data", "Inspect OPUS spectra and reference sheets"),
    ("2", "Configure", "Choose properties and validation settings"),
    ("3", "Run", "Monitor analysis progress and logs"),
    ("4", "Results", "Review metrics, plots, and model choices"),
    ("5", "Predict", "Apply saved models to new spectra"),
]
for col, (number, title, description) in zip(cols, steps):
    with col:
        st.metric(f"Step {number}", title)
        st.caption(description)

st.subheader("Local-first design")
st.write(
    "Your full spectra and laboratory reference data stay on your computer. GitLab CI uses only "
    "a small representative fixture for automated development tests."
)
