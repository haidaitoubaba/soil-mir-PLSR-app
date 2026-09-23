from __future__ import annotations

import streamlit as st

from soil_mir.config import SpectralConfig, ValidationConfig

st.set_page_config(page_title="Configure | Soil MIR PLSR", page_icon="🌱", layout="wide")
st.title("Configuration")
st.caption("Choose common modelling settings. Property metadata remains property-specific.")

available_properties = st.session_state.get("soil_mir_properties", [])
if not available_properties:
    st.warning("Inspect a spectra folder and reference workbook on the Data page first.")
    st.stop()

default_properties = [
    prop for prop in ("202_STC", "202_STN") if prop in available_properties
] or available_properties[:1]

selected_properties = st.multiselect(
    "Properties",
    available_properties,
    default=st.session_state.get("soil_mir_selected_properties", default_properties),
)

st.subheader("Basic settings")
left, right = st.columns(2)

with left:
    wn_range = st.slider(
        "Spectral range (cm⁻¹)",
        min_value=400,
        max_value=4000,
        value=st.session_state.get("soil_mir_wn_range", (600, 4000)),
        step=25,
    )
    exclude_co2 = st.checkbox(
        "Exclude CO₂ region (2300–2400 cm⁻¹)",
        value=st.session_state.get("soil_mir_exclude_co2", False),
    )
    max_rank = st.number_input(
        "Maximum PLS rank",
        min_value=1,
        max_value=50,
        value=st.session_state.get("soil_mir_max_rank", 15),
        step=1,
    )

with right:
    validation_methods = st.multiselect(
        "Validation methods",
        ["kfold", "monte_carlo", "loso", "logo", "kennard_stone"],
        default=st.session_state.get("soil_mir_validation_methods", ["kfold"]),
    )
    region_windows = st.number_input(
        "Region search windows",
        min_value=1,
        max_value=16,
        value=st.session_state.get("soil_mir_region_windows", 7),
        step=1,
        help="The search grows exponentially as the number of windows increases.",
    )
    tolerance = st.number_input(
        "RMSECV tolerance (%)",
        min_value=0.0,
        value=float(st.session_state.get("soil_mir_tolerance", 5.0)),
        step=0.5,
    )

with st.expander("Advanced settings"):
    sg_window = st.number_input(
        "Savitzky–Golay window",
        min_value=3,
        value=st.session_state.get("soil_mir_sg_window", 11),
        step=2,
    )
    sg_polyorder = st.number_input(
        "Savitzky–Golay polynomial order",
        min_value=0,
        value=st.session_state.get("soil_mir_sg_polyorder", 2),
        step=1,
    )
    random_seed = st.number_input(
        "Random seed",
        min_value=0,
        value=st.session_state.get("soil_mir_random_seed", 42),
        step=1,
    )

if st.button("Validate and save configuration", type="primary"):
    try:
        spectral = SpectralConfig(
            wn_min=float(wn_range[0]),
            wn_max=float(wn_range[1]),
            exclude_co2=exclude_co2,
            sg_window=int(sg_window),
            sg_polyorder=int(sg_polyorder),
        )
        validation = ValidationConfig(
            methods=tuple(validation_methods),
            max_rank=int(max_rank),
            region_search_n_windows=int(region_windows),
            rmsecv_tolerance_pct=float(tolerance),
            random_seed=int(random_seed),
        )
        spectral.validate()
        validation.validate()
        if not selected_properties:
            raise ValueError("Select at least one property.")
        if not validation_methods:
            raise ValueError("Select at least one validation method.")
    except Exception as exc:
        st.error(str(exc))
    else:
        st.session_state["soil_mir_selected_properties"] = selected_properties
        st.session_state["soil_mir_wn_range"] = tuple(wn_range)
        st.session_state["soil_mir_exclude_co2"] = exclude_co2
        st.session_state["soil_mir_max_rank"] = int(max_rank)
        st.session_state["soil_mir_validation_methods"] = validation_methods
        st.session_state["soil_mir_region_windows"] = int(region_windows)
        st.session_state["soil_mir_tolerance"] = float(tolerance)
        st.session_state["soil_mir_sg_window"] = int(sg_window)
        st.session_state["soil_mir_sg_polyorder"] = int(sg_polyorder)
        st.session_state["soil_mir_random_seed"] = int(random_seed)
        st.success("Configuration is valid and saved for this session.")
