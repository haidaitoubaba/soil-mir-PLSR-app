from __future__ import annotations

import math
from copy import deepcopy

import streamlit as st

from soil_mir.ui_state import section_navigation

from soil_mir.config import (
    SpectralConfig,
    ValidationConfig,
)
from soil_mir.preprocessing import (
    LEGACY_PREPROCESSING_NAMES,
    PREPROCESSING_NAMES,
    configured_preprocessing_methods,
)
from soil_mir.methods import (
    VALIDATION_METHOD_LABELS,
    validation_method_description,
    validation_method_label,
)
from soil_mir.services.profiles import (
    PROFILE_WIDGET_KEYS,
    delete_profile,
    list_profiles,
    load_profile,
    profile_widget_updates,
    save_profile,
)

st.title("Configuration")
st.caption(
    "Choose modelling and validation settings. "
    "Property metadata remains property-specific."
)

section = section_navigation("configuration")

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
    st.session_state[widget_key] = value


_initialize_widget_state(
    "soil_mir_selected_properties",
    list(default_properties),
)
# Profiles and saved runs can supply a range before the widgets are rendered.
pending_range = st.session_state.pop(PROFILE_WIDGET_KEYS["soil_mir_wn_range"], None)
initial_range = (
    pending_range
    if pending_range is not None
    else st.session_state.get("soil_mir_wn_range", (600.0, 4000.0))
)
for key, bound in zip(("cfg_wn_min", "cfg_wn_max"), initial_range):
    if pending_range is not None or key not in st.session_state:
        st.session_state[key] = float(bound)
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
    "soil_mir_use_group_stratification",
    True,
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
    "soil_mir_preprocessing_methods",
    list(LEGACY_PREPROCESSING_NAMES),
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
    "soil_mir_use_group_stratification",
    "soil_mir_region_windows",
    "soil_mir_tolerance",
    "soil_mir_sg_window",
    "soil_mir_sg_polyorder",
    "soil_mir_preprocessing_methods",
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
# Existing cfg_* and ref_* keys remain durable drafts, not widget keys.
# Saved profiles and history can still populate them via the existing service.
def cfg_widget(container, kind, label, *args, key, **kwargs):
    widget_key = f"_rc6_cfg_{key}"
    state = st.session_state
    if widget_key not in state or state[widget_key] != state[key]:
        state[widget_key] = deepcopy(state[key])

    def store():
        state[key] = deepcopy(state[widget_key])

    result = getattr(container, kind)(label, *args, key=widget_key, on_change=store, **kwargs)
    state[key] = deepcopy(result)
    return result


def draft(config_key):
    return st.session_state[PROFILE_WIDGET_KEYS[config_key]]


st.session_state["cfg_selected_properties"] = [
    prop for prop in draft("soil_mir_selected_properties") if prop in available_properties
]

if section == "Profiles" and output_dir:
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
                        # Older profiles reproduce the original four-method search.
                        allowed.setdefault(
                            "soil_mir_preprocessing_methods",
                            list(LEGACY_PREPROCESSING_NAMES),
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
                        st.session_state.rc6_configuration_dirty = False
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

elif section == "General":
    selected_properties = cfg_widget(st, "multiselect",
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

    st.markdown("**Training spectral range (cm⁻¹)**")
    lower_col, upper_col = st.columns(2)
    lower = cfg_widget(lower_col, "number_input",
        "Minimum (cm⁻¹)",
        min_value=400.0,
        max_value=4000.0,
        step=0.0001,
        format="%.4f",
        key="cfg_wn_min",
    )
    upper = cfg_widget(upper_col, "number_input",
        "Maximum (cm⁻¹)",
        min_value=400.0,
        max_value=4000.0,
        step=0.0001,
        format="%.4f",
        key="cfg_wn_max",
    )
    wn_range = (lower, upper)
    st.caption("Only measured points within these bounds enter calibration.")
    exclude_co2 = cfg_widget(st, "checkbox",
        "Exclude CO₂ region (2300–2400 cm⁻¹)",
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_exclude_co2"
        ],
        help=(
            "Property Metadata takes precedence when "
            "a property-specific setting is available."
        ),
    )

elif section == "Validation":
    validation_methods = cfg_widget(st, "multiselect",
        "Validation methods",
        list(
            VALIDATION_METHOD_LABELS
        ),
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_validation_methods"
        ],
        format_func=validation_method_label,
        help=(
            "Choose one or more outer-validation designs. "
            "The full names shown here are display labels; "
            "saved method keys remain unchanged for compatibility."
        ),
    )
    with st.expander(
        "What do these validation methods mean?"
    ):
        for method in VALIDATION_METHOD_LABELS:
            st.markdown(
                f"**{validation_method_label(method)}** — "
                f"{validation_method_description(method)}"
            )
    st.subheader("Validation settings")
    use_group_stratification = cfg_widget(st, "checkbox",
        "Use Group for stratification when available",
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_use_group_stratification"
        ],
        help=(
            "When enabled, K-fold and Monte Carlo use complete Group metadata "
            "for stratification when feasible. When disabled, they ignore Group "
            "and split at the sample level. LOSO and Kennard–Stone are unaffected; "
            "LOGO always requires and uses Group."
        ),
    )
    validation_left, validation_right = st.columns(2)

    with validation_left:
        internal_cv_folds = cfg_widget(st, "number_input",
            "Internal CV folds",
            min_value=2,
            max_value=20,
            step=1,
            key=PROFILE_WIDGET_KEYS[
                "soil_mir_internal_cv_folds"
            ],
        )
        outer_cv_folds = cfg_widget(st, "number_input",
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
        n_repeats = cfg_widget(st, "number_input",
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
        validation_fraction = cfg_widget(st, "number_input",
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
        ks_representation = cfg_widget(st, "selectbox",
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
        ks_pca_variance = cfg_widget(st, "number_input",
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

    random_seed = cfg_widget(st, "number_input",
        "Random seed",
        min_value=0,
        step=1,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_random_seed"
        ],
    )

elif section == "Preprocessing":
    st.subheader("PLSR preprocessing candidates")
    preprocessing_methods = cfg_widget(st, "multiselect",
        "Preprocessing methods to compare",
        list(PREPROCESSING_NAMES),
        key=PROFILE_WIDGET_KEYS["soil_mir_preprocessing_methods"],
        help=(
            "Nested model selection compares every selected method. "
            "All 11 methods are available; the original four are selected by default "
            "to preserve earlier workloads. More methods increase run time."
        ),
    )
    st.caption(
        f"{len(preprocessing_methods)} of {len(PREPROCESSING_NAMES)} candidates selected. "
        "SG smoothing and derivatives operate separately within each spectral interval."
    )

    sg_window = cfg_widget(st, "number_input",
        "Savitzky–Golay window",
        min_value=3,
        step=2,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_sg_window"
        ],
    )
    sg_polyorder = cfg_widget(st, "number_input",
        "Savitzky–Golay polynomial order",
        min_value=0,
        step=1,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_sg_polyorder"
        ],
    )

elif section == "Advanced":
    max_rank = cfg_widget(st, "number_input",
        "Maximum PLS rank",
        min_value=1,
        max_value=50,
        step=1,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_max_rank"
        ],
    )
    region_windows = cfg_widget(st, "number_input",
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
    tolerance = cfg_widget(st, "number_input",
        "RMSECV tolerance (%)",
        min_value=0.0,
        step=0.5,
        key=PROFILE_WIDGET_KEYS[
            "soil_mir_tolerance"
        ],
    )
    with st.expander("Performance settings"):
        st.caption(
            "Outer validation splits can run in parallel. "
            "Keep the inner numerical thread limit at 1 to avoid "
            "nested BLAS/OpenMP oversubscription."
        )
        outer_n_jobs = cfg_widget(st, "number_input",
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
        inner_thread_limit = cfg_widget(st, "number_input",
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


selected_properties = draft("soil_mir_selected_properties")
wn_range = (st.session_state["cfg_wn_min"], st.session_state["cfg_wn_max"])
exclude_co2 = draft("soil_mir_exclude_co2")
max_rank = draft("soil_mir_max_rank")
validation_methods = draft("soil_mir_validation_methods")
region_windows = draft("soil_mir_region_windows")
tolerance = draft("soil_mir_tolerance")
use_group_stratification = draft("soil_mir_use_group_stratification")
internal_cv_folds = draft("soil_mir_internal_cv_folds")
outer_cv_folds = draft("soil_mir_outer_cv_folds")
n_repeats = draft("soil_mir_n_repeats")
validation_fraction = draft("soil_mir_validation_fraction")
ks_representation = draft("soil_mir_ks_representation")
ks_pca_variance = draft("soil_mir_ks_pca_variance")
preprocessing_methods = draft("soil_mir_preprocessing_methods")
sg_window = draft("soil_mir_sg_window")
sg_polyorder = draft("soil_mir_sg_polyorder")
random_seed = draft("soil_mir_random_seed")
outer_n_jobs = draft("soil_mir_outer_n_jobs")
inner_thread_limit = draft("soil_mir_inner_thread_limit")

saved_reference_ranges = st.session_state.get(
    "soil_mir_reference_ranges",
    {},
)
reference_range_inputs = {}
if section == "Advanced":
    st.subheader("Reference-value filters (optional)")
    st.caption(
        "Leave a field blank for no limit. "
        "Limits are applied separately to each property before validation."
    )
for property_name in selected_properties:
    saved = saved_reference_ranges.get(
        property_name,
        {},
    )
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
    if section == "Advanced":
        left_range, right_range = st.columns(2)
        ref_min_text = cfg_widget(left_range, "text_input", f"{property_name} minimum", key=min_key)
        ref_max_text = cfg_widget(
            right_range, "text_input", f"{property_name} maximum", key=max_key
        )
    else:
        ref_min_text = st.session_state[min_key]
        ref_max_text = st.session_state[max_key]
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
        "soil_mir_use_group_stratification": bool(
            use_group_stratification
        ),
        "soil_mir_region_windows": int(region_windows),
        "soil_mir_tolerance": float(tolerance),
        "soil_mir_sg_window": int(sg_window),
        "soil_mir_sg_polyorder": int(sg_polyorder),
        "soil_mir_preprocessing_methods": list(preprocessing_methods),
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
    configured_preprocessing_methods(
        {
            "preprocessing_methods": list(preprocessing_methods),
            "sg_polyorder": int(sg_polyorder),
        }
    )
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


try:
    edited = current_values()
    st.session_state.rc6_configuration_dirty = any(
        st.session_state.get(key) != value for key, value in edited.items()
    )
except (ValueError, TypeError):
    st.session_state.rc6_configuration_dirty = True

st.divider()
st.caption(
    f"Properties: {', '.join(selected_properties) or 'None'} | "
    f"Range: {wn_range[0]:g}–{wn_range[1]:g} cm⁻¹ | "
    f"Validation: {', '.join(map(validation_method_label, validation_methods)) or 'None'} | "
    f"{len(preprocessing_methods)} preprocessing candidates | Seed {random_seed} | "
    f"Group stratification: {'on' if use_group_stratification else 'off'} | "
    f"CO₂ exclusion: {'on' if exclude_co2 else 'off'}"
)
if st.session_state.rc6_configuration_dirty:
    st.warning("Unapplied configuration edits. Validate and save before starting a new run.")
else:
    st.success("Configuration is applied.")

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
        st.session_state.rc6_configuration_dirty = False
        st.success(
            "Configuration is valid and saved for this session."
        )

if section == "Profiles" and output_dir:
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
            st.session_state.rc6_configuration_dirty = False
            st.success(
                f"Saved configuration profile: {path.name}"
            )
