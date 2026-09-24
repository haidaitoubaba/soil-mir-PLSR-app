from __future__ import annotations

import math

import streamlit as st

from soil_mir.config import (
    SpectralConfig,
    ValidationConfig,
)
from soil_mir.services.profiles import (
    PROFILE_WIDGET_KEYS,
    delete_profile,
    list_profiles,
    load_profile,
    profile_widget_updates,
    save_profile,
)

st.set_page_config(
    page_title="Configure | Soil MIR PLSR",
    page_icon="🌱",
    layout="wide",
)
st.title("Configuration")
st.caption(
    "Choose modelling and validation settings. "
    "Property metadata remains property-specific."
)

available_properties = st.session_state.get(
    "soil_mir_properties",
    [],
)
if not available_properties:
    st.warning(
        "Inspect a spectra folder and reference workbook "
        "on the Data page first."
    )
    st.stop()

default_properties = []


def _initialize_widget_state(
    config_key: str,
    default,
) -> None:
    widget_key = PROFILE_WIDGET_KEYS[
        config_key
    ]
    if widget_key in st.session_state:
        return
    value = st.session_state.get(
        config_key,
        default,
    )
    if config_key == "soil_mir_selected_properties":
        value = [
            prop
            for prop in value
            if prop in available_properties
        ]
    if config_key == "soil_mir_wn_range":
        value = tuple(value)
    st.session_state[widget_key] = value


_initialize_widget_state(
    "soil_mir_selected_properties",
    list(default_properties),
)
_initialize_widget_state(
    "soil_mir_wn_range",
    (600, 4000),
)
_initialize_widget_state(
    "soil_mir_exclude_co2",
    False,
)
_initialize_widget_state(
    "soil_mir_max_rank",
    15,
)
_initialize_widget_state(
    "soil_mir_validation_methods",
    ["kfold"],
)
_initialize_widget_state(
    "soil_mir_region_windows",
    7,
)
_initialize_widget_state(
    "soil_mir_tolerance",
    5.0,
)
_initialize_widget_state(
    "soil_mir_sg_window",
    11,
)
_initialize_widget_state(
    "soil_mir_sg_polyorder",
    2,
)
_initialize_widget_state(
    "soil_mir_random_seed",
    42,
)
_initialize_widget_state(
    "soil_mir_internal_cv_folds",
    10,
)
_initialize_widget_state(
    "soil_mir_outer_cv_folds",
    5,
)
_initialize_widget_state(
    "soil_mir_n_repeats",
    30,
)
_initialize_widget_state(
    "soil_mir_validation_fraction",
    0.20,
)
_initialize_widget_state(
    "soil_mir_ks_representation",
    "raw",
)
_initialize_widget_state(
    "soil_mir_ks_pca_variance",
    0.99,
)
_initialize_widget_state(
    "soil_mir_outer_n_jobs",
    4,
)
_initialize_widget_state(
    "soil_mir_inner_thread_limit",
    1,
)

PROFILE_SESSION_KEYS = {
    "soil_mir_selected_properties",
    "soil_mir_wn_range",
    "soil_mir_exclude_co2",
    "soil_mir_max_rank",
    "soil_mir_validation_methods",
    "soil_mir_region_windows",
    "soil_mir_tolerance",
    "soil_mir_sg_window",
    "soil_mir_sg_polyorder",
    "soil_mir_random_seed",
    "soil_mir_internal_cv_folds",
    "soil_mir_outer_cv_folds",
    "soil_mir_n_repeats",
    "soil_mir_validation_fraction",
    "soil_mir_ks_representation",
    "soil_mir_ks_pca_variance",
    "soil_mir_outer_n_jobs",
    "soil_mir_inner_thread_limit",
    "soil_mir_reference_ranges",
}

output_dir = st.session_state.get(
    "soil_mir_output_dir",
    "",
)
if output_dir:
    with st.expander("Saved configuration profiles"):
        profiles = list_profiles(output_dir)
        if profiles:
            selected_profile = st.selectbox(
                "Profile",
                list(profiles),
                key="configuration_profile_selector",
            )
            load_col, delete_col = st.columns(
                [3, 2]
            )
            with load_col:
                if st.button(
                    "Load selected profile",
                    key="load_configuration_profile",
                    use_container_width=True,
                ):
                    try:
                        loaded = load_profile(
                            profiles[selected_profile]
                        )
                    except Exception as exc:
                        st.error(str(exc))
                    else:
                        allowed = {
                            key: value
                            for key, value in loaded.items()
                            if key in PROFILE_SESSION_KEYS
                        }
                        if "soil_mir_selected_properties" in allowed:
                            allowed[
                                "soil_mir_selected_properties"
                            ] = [
                                prop
                                for prop in allowed[
                                    "soil_mir_selected_properties"
                                ]
                                if prop in available_properties
                            ]
                        if "soil_mir_wn_range" in allowed:
                            allowed[
                                "soil_mir_wn_range"
                            ] = tuple(
                                allowed[
                                    "soil_mir_wn_range"
                                ]
                            )
                        st.session_state.update(
                            allowed
                        )
                        st.session_state.update(
                            profile_widget_updates(
                                allowed,
                                available_properties,
                            )
                        )
                        st.session_state.pop(
                            "soil_mir_profile_delete_pending",
                            None,
                        )
                        st.rerun()

            with delete_col:
                if st.button(
                    "Delete selected profile",
                    key="delete_configuration_profile",
                    use_container_width=True,
                ):
                    st.session_state[
                        "soil_mir_profile_delete_pending"
                    ] = selected_profile

            pending_delete = st.session_state.get(
                "soil_mir_profile_delete_pending"
            )
            if pending_delete:
                if pending_delete not in profiles:
                    st.session_state.pop(
                        "soil_mir_profile_delete_pending",
                        None,
                    )
                    st.rerun()

                st.warning(
                    "Delete configuration profile "
                    f"**{pending_delete}**? "
                    "This deletes only its saved profile JSON. "
                    "Run history, models, and result files are not affected."
                )
                confirm_col, cancel_col = st.columns(
                    2
                )
                with confirm_col:
                    if st.button(
                        "Confirm delete",
                        key="confirm_delete_configuration_profile",
                        type="primary",
                        use_container_width=True,
                    ):
                        try:
                            delete_profile(
                                output_dir,
                                pending_delete,
                            )
                        except Exception as exc:
                            st.error(str(exc))
                        else:
                            st.session_state.pop(
                                "soil_mir_profile_delete_pending",
                                None,
                            )
                            st.session_state.pop(
                                "configuration_profile_selector",
                                None,
                            )
                            st.rerun()
                with cancel_col:
                    if st.button(
                        "Cancel",
                        key="cancel_delete_configuration_profile",
                        use_container_width=True,
                    ):
                        st.session_state.pop(
                            "soil_mir_profile_delete_pending",
                            None,
                        )
                        st.rerun()
        else:
            st.caption(
                "No saved profiles yet. Validate settings below, "
                "then save the configuration as a profile."
            )

selected_properties = st.multiselect(
    "Properties",
    available_properties,
    key=PROFILE_WIDGET_KEYS[
        "soil_mir_selected_properties"
    ],
    placeholder="Choose one or more properties",
    help=(
        "No property is selected automatically. "
        "Choose explicitly or load a saved profile."
    ),
)

st.subheader("Basic settings")
left, right = st.columns(2)

with left:
    wn_range = st.slider(
        "Spectral range (cm⁻¹)",
        min_value=400,
        max_value=4000,
        step=25,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_wn_range"
        ],
    )
    exclude_co2 = st.checkbox(
        "Exclude CO₂ region (2300–2400 cm⁻¹)",
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_exclude_co2"
        ],
        help=(
            "Property Metadata takes precedence when "
            "a property-specific setting is available."
        ),
    )
    max_rank = st.number_input(
        "Maximum PLS rank",
        min_value=1,
        max_value=50,
        step=1,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_max_rank"
        ],
    )

with right:
    validation_methods = st.multiselect(
        "Validation methods",
        [
            "kfold",
            "monte_carlo",
            "loso",
            "logo",
            "kennard_stone",
        ],
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_validation_methods"
        ],
    )
    region_windows = st.number_input(
        "Region search windows",
        min_value=1,
        max_value=16,
        step=1,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_region_windows"
        ],
        help=(
            "Backward search cost grows quickly as "
            "the number of windows increases."
        ),
    )
    tolerance = st.number_input(
        "RMSECV tolerance (%)",
        min_value=0.0,
        step=0.5,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_tolerance"
        ],
    )

st.subheader("Validation settings")
validation_left, validation_right = st.columns(2)

with validation_left:
    internal_cv_folds = st.number_input(
        "Internal CV folds",
        min_value=2,
        max_value=20,
        step=1,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_internal_cv_folds"
        ],
    )
    outer_cv_folds = st.number_input(
        "Outer K-fold folds",
        min_value=2,
        max_value=20,
        step=1,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_outer_cv_folds"
        ],
        disabled=(
            "kfold"
            not in validation_methods
        ),
    )
    n_repeats = st.number_input(
        "Monte Carlo repeats",
        min_value=1,
        max_value=500,
        step=1,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_n_repeats"
        ],
        disabled=(
            "monte_carlo"
            not in validation_methods
        ),
    )

with validation_right:
    validation_fraction = st.number_input(
        "Holdout fraction",
        min_value=0.05,
        max_value=0.95,
        step=0.05,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_validation_fraction"
        ],
        disabled=(
            not any(
                method in validation_methods
                for method in (
                    "monte_carlo",
                    "kennard_stone",
                )
            )
        ),
    )
    ks_representation = st.selectbox(
        "Kennard–Stone representation",
        [
            "raw",
            "derivative_snv",
            "pca",
        ],
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_ks_representation"
        ],
        disabled=(
            "kennard_stone"
            not in validation_methods
        ),
    )
    ks_pca_variance = st.number_input(
        "KS PCA retained variance",
        min_value=0.50,
        max_value=0.999,
        step=0.01,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_ks_pca_variance"
        ],
        disabled=(
            "kennard_stone"
            not in validation_methods
            or ks_representation != "pca"
        ),
    )

with st.expander("Advanced spectral settings"):
    sg_window = st.number_input(
        "Savitzky–Golay window",
        min_value=3,
        step=2,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_sg_window"
        ],
    )
    sg_polyorder = st.number_input(
        "Savitzky–Golay polynomial order",
        min_value=0,
        step=1,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_sg_polyorder"
        ],
    )
    random_seed = st.number_input(
        "Random seed",
        min_value=0,
        step=1,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_random_seed"
        ],
    )


with st.expander("Performance settings"):
    st.caption(
        "Outer validation splits can run in parallel. "
        "Keep the inner numerical thread limit at 1 to avoid "
        "nested BLAS/OpenMP oversubscription."
    )
    outer_n_jobs = st.number_input(
        "Outer parallel workers",
        min_value=1,
        max_value=32,
        step=1,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_outer_n_jobs"
        ],
        help=(
            "Legacy default is 4. A value of 1 runs outer splits "
            "sequentially."
        ),
    )
    inner_thread_limit = st.number_input(
        "Inner numerical threads per worker",
        min_value=1,
        max_value=8,
        step=1,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_inner_thread_limit"
        ],
        help=(
            "Legacy default is 1. Increasing this while also using "
            "multiple outer workers can reduce performance."
        ),
    )

saved_reference_ranges = st.session_state.get(
    "soil_mir_reference_ranges",
    {},
)
reference_range_inputs = {}
with st.expander("Reference-value filters (optional)"):
    st.caption(
        "Leave a field blank for no limit. "
        "Limits are applied separately to each property before validation."
    )
    for property_name in selected_properties:
        saved = saved_reference_ranges.get(
            property_name,
            {},
        )
        left_range, right_range = st.columns(2)
        min_key = f"ref_min_{property_name}"
        max_key = f"ref_max_{property_name}"
        if min_key not in st.session_state:
            st.session_state[min_key] = (
                ""
                if saved.get("min") is None
                else str(saved.get("min"))
            )
        if max_key not in st.session_state:
            st.session_state[max_key] = (
                ""
                if saved.get("max") is None
                else str(saved.get("max"))
            )
        with left_range:
            ref_min_text = st.text_input(
                f"{property_name} minimum",
                key=min_key,
            )
        with right_range:
            ref_max_text = st.text_input(
                f"{property_name} maximum",
                key=max_key,
            )
        reference_range_inputs[property_name] = {
            "min": ref_min_text,
            "max": ref_max_text,
        }


def parsed_reference_ranges() -> dict:
    parsed = {}
    for property_name, values in reference_range_inputs.items():
        bounds = {}
        for bound in ("min", "max"):
            text = str(values[bound]).strip()
            if not text:
                bounds[bound] = None
                continue
            try:
                value = float(text)
            except ValueError as exc:
                raise ValueError(
                    f"{property_name} {bound} must be numeric or blank."
                ) from exc
            if not math.isfinite(value):
                raise ValueError(
                    f"{property_name} {bound} must be finite or blank."
                )
            bounds[bound] = value

        if (
            bounds["min"] is not None
            and bounds["max"] is not None
            and bounds["min"] > bounds["max"]
        ):
            raise ValueError(
                f"{property_name} minimum must not exceed maximum."
            )
        parsed[property_name] = bounds
    return parsed


def current_values() -> dict:
    return {
        "soil_mir_selected_properties": selected_properties,
        "soil_mir_wn_range": tuple(wn_range),
        "soil_mir_exclude_co2": exclude_co2,
        "soil_mir_max_rank": int(max_rank),
        "soil_mir_validation_methods": validation_methods,
        "soil_mir_region_windows": int(region_windows),
        "soil_mir_tolerance": float(tolerance),
        "soil_mir_sg_window": int(sg_window),
        "soil_mir_sg_polyorder": int(sg_polyorder),
        "soil_mir_random_seed": int(random_seed),
        "soil_mir_internal_cv_folds": int(internal_cv_folds),
        "soil_mir_outer_cv_folds": int(outer_cv_folds),
        "soil_mir_n_repeats": int(n_repeats),
        "soil_mir_validation_fraction": float(validation_fraction),
        "soil_mir_ks_representation": ks_representation,
        "soil_mir_ks_pca_variance": float(ks_pca_variance),
        "soil_mir_outer_n_jobs": int(outer_n_jobs),
        "soil_mir_inner_thread_limit": int(
            inner_thread_limit
        ),
        "soil_mir_reference_ranges": parsed_reference_ranges(),
    }


def validate_current_configuration() -> dict:
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
    if not 0 < float(validation_fraction) < 1:
        raise ValueError(
            "Holdout fraction must be between 0 and 1."
        )
    if int(outer_n_jobs) < 1:
        raise ValueError(
            "Outer parallel workers must be at least 1."
        )
    if int(inner_thread_limit) < 1:
        raise ValueError(
            "Inner numerical threads must be at least 1."
        )
    return current_values()


if st.button(
    "Validate and save configuration",
    type="primary",
):
    try:
        values = validate_current_configuration()
    except Exception as exc:
        st.error(str(exc))
    else:
        st.session_state.update(values)
        st.success(
            "Configuration is valid and saved for this session."
        )

if output_dir:
    st.subheader("Save profile")
    profile_name = st.text_input(
        "Profile name",
        value="",
        placeholder="e.g. STC-STN nested kfold",
    )
    if st.button(
        "Save current settings as profile",
        disabled=not profile_name.strip(),
    ):
        try:
            values = validate_current_configuration()
            path = save_profile(
                output_dir,
                profile_name,
                values,
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            st.session_state.update(values)
            st.success(
                f"Saved configuration profile: {path.name}"
            )
