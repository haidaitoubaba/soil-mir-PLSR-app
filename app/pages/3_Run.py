from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from soil_mir.reporting import (
    read_run_manifest,
)
from soil_mir.services.history import (
    pending_run_keys,
)
from soil_mir.methods import (
    validation_method_label,
)
from soil_mir.services.calibration import (
    load_calibration_dataset,
    preflight_validation_methods,
)
from soil_mir.services.run_control import (
    start_validation_job,
)


st.set_page_config(
    page_title="Run | Soil MIR PLSR",
    page_icon="🌱",
    layout="wide",
)
st.title("Run")
st.caption(
    "Preflight first, then nested model selection and outer validation."
)

required = [
    "soil_mir_spectra_dir",
    "soil_mir_reference_excel",
    "soil_mir_output_dir",
    "soil_mir_selected_properties",
    "soil_mir_validation_methods",
    "soil_mir_internal_cv_folds",
]
missing = [
    key
    for key in required
    if not st.session_state.get(key)
]
if missing:
    st.warning(
        "Complete Data inspection and save Configuration first."
    )
    st.stop()

properties = list(
    st.session_state["soil_mir_selected_properties"]
)
methods = list(
    st.session_state["soil_mir_validation_methods"]
)
reference_ranges = st.session_state.get(
    "soil_mir_reference_ranges",
    {},
)


def analysis_settings() -> dict:
    return {
        "max_rank": int(
            st.session_state["soil_mir_max_rank"]
        ),
        "region_search_n_windows": int(
            st.session_state["soil_mir_region_windows"]
        ),
        "rmsecv_tolerance_pct": float(
            st.session_state["soil_mir_tolerance"]
        ),
        "sg_window": int(
            st.session_state["soil_mir_sg_window"]
        ),
        "sg_polyorder": int(
            st.session_state["soil_mir_sg_polyorder"]
        ),
        "random_seed": int(
            st.session_state["soil_mir_random_seed"]
        ),
        "internal_cv_folds": int(
            st.session_state[
                "soil_mir_internal_cv_folds"
            ]
        ),
        "outer_cv_folds": int(
            st.session_state.get(
                "soil_mir_outer_cv_folds",
                5,
            )
        ),
        "n_repeats": int(
            st.session_state.get(
                "soil_mir_n_repeats",
                30,
            )
        ),
        "validation_fraction": float(
            st.session_state.get(
                "soil_mir_validation_fraction",
                0.20,
            )
        ),
        "ks_representation": str(
            st.session_state.get(
                "soil_mir_ks_representation",
                "raw",
            )
        ),
        "ks_pca_variance": float(
            st.session_state.get(
                "soil_mir_ks_pca_variance",
                0.99,
            )
        ),
        "wn_min": float(
            st.session_state[
                "soil_mir_wn_range"
            ][0]
        ),
        "wn_max": float(
            st.session_state[
                "soil_mir_wn_range"
            ][1]
        ),
        "outer_n_jobs": int(
            st.session_state.get(
                "soil_mir_outer_n_jobs",
                4,
            )
        ),
        "inner_thread_limit": int(
            st.session_state.get(
                "soil_mir_inner_thread_limit",
                1,
            )
        ),
    }


settings = analysis_settings()
cache_root = (
    Path(
        st.session_state[
            "soil_mir_output_dir"
        ]
    )
    / ".soil_mir_cache"
)

st.write(
    f"Properties: **{', '.join(properties)}**"
)
st.write(
    "Validation methods: **"
    + ", ".join(
        validation_method_label(
            method
        )
        for method in methods
    )
    + "**"
)
st.write(
    "Results directory: "
    f"{st.session_state['soil_mir_output_dir']}"
)
st.write(
    "Performance: "
    f"**{settings['outer_n_jobs']} outer workers**, "
    f"**{settings['inner_thread_limit']} inner numerical thread(s) per worker**"
)


resume_run_dir_text = st.session_state.get(
    "soil_mir_resume_run_dir",
    "",
)
resume_manifest = None
if resume_run_dir_text:
    try:
        resume_manifest = read_run_manifest(
            resume_run_dir_text
        )
    except Exception as exc:
        st.warning(
            "The selected run can no longer be resumed: "
            f"{exc}"
        )
        st.session_state.pop(
            "soil_mir_resume_run_dir",
            None,
        )
        resume_run_dir_text = ""
    else:
        pending = pending_run_keys(
            resume_manifest
        )
        st.info(
            "Resume mode: "
            f"{resume_manifest.get('run_id', Path(resume_run_dir_text).name)}. "
            f"{len(resume_manifest.get('results', []))} analysis combination(s) "
            f"already completed; {len(pending)} remain. "
            "Preflight will run again, and completed combinations will be skipped."
        )

if "loso" in methods:
    st.warning(
        "LOSO can be computationally expensive because "
        "it fits one nested model per sample."
    )
if "monte_carlo" in methods:
    st.warning(
        "Monte Carlo runtime grows with the number of repeats."
    )


preflight_payload = {
    "spectra_dir": st.session_state[
        "soil_mir_spectra_dir"
    ],
    "reference_excel": st.session_state[
        "soil_mir_reference_excel"
    ],
    "output_dir": st.session_state[
        "soil_mir_output_dir"
    ],
    "properties": properties,
    "methods": methods,
    "settings": settings,
    "reference_ranges": reference_ranges,
    "fallback_exclude_co2": bool(
        st.session_state.get(
            "soil_mir_exclude_co2",
            False,
        )
    ),
}
preflight_signature = json.dumps(
    preflight_payload,
    sort_keys=True,
    default=str,
)

if (
    st.session_state.get(
        "soil_mir_preflight_signature"
    )
    != preflight_signature
):
    for key in (
        "soil_mir_preflight_table",
        "soil_mir_preflight_datasets",
        "soil_mir_preflight_passed",
        "soil_mir_preflight_signature",
    ):
        st.session_state.pop(
            key,
            None,
        )

st.subheader("1. Preflight")
st.caption(
    "Preflight loads the selected real data, applies any reference-value "
    "filters, verifies spectral coverage, and checks whether every selected "
    "validation design is feasible. It does not fit the nested PLSR models."
)

preflight_exists = (
    st.session_state.get(
        "soil_mir_preflight_signature"
    )
    == preflight_signature
    and "soil_mir_preflight_table"
    in st.session_state
)

active_job = st.session_state.get(
    "soil_mir_active_validation_job"
)
run_is_active = active_job is not None

if st.button(
    (
        "Re-run preflight check"
        if preflight_exists
        else "Run preflight check"
    ),
    type="secondary",
    disabled=run_is_active,
):
    datasets = {}
    preflight_frames = []
    try:
        with st.status(
            "Running preflight",
            expanded=True,
        ) as preflight_status:
            for property_sheet in properties:
                st.write(
                    f"Reading and validating {property_sheet}..."
                )
                property_range = (
                    reference_ranges.get(
                        property_sheet,
                        {},
                    )
                )
                dataset = load_calibration_dataset(
                    st.session_state[
                        "soil_mir_spectra_dir"
                    ],
                    st.session_state[
                        "soil_mir_reference_excel"
                    ],
                    property_sheet,
                    wn_min=settings["wn_min"],
                    wn_max=settings["wn_max"],
                    fallback_exclude_co2=bool(
                        st.session_state.get(
                            "soil_mir_exclude_co2",
                            False,
                        )
                    ),
                    cache_root=cache_root,
                    ref_min=property_range.get(
                        "min"
                    ),
                    ref_max=property_range.get(
                        "max"
                    ),
                )
                datasets[property_sheet] = dataset
                st.write(
                    f"{property_sheet}: "
                    f"{dataset.rows:,} spectra, "
                    f"{dataset.unique_samples:,} samples, "
                    f"{len(dataset.wavenumbers):,} retained spectral points; "
                    f"cache {dataset.cache_hits} reused / "
                    f"{dataset.cache_misses} parsed."
                )
                if (
                    dataset.endpoint_trimmed_points
                ):
                    st.write(
                        "Shared-grid alignment trimmed "
                        f"{dataset.endpoint_trimmed_points} "
                        "endpoint point(s) from the modal OPUS grid; "
                        "no extrapolation was used."
                    )
                if (
                    dataset.excluded_reference_rows
                ):
                    st.write(
                        "Reference filter excluded "
                        f"{dataset.excluded_reference_rows:,} rows from "
                        f"{dataset.excluded_reference_samples:,} samples."
                    )

                preflight_frames.append(
                    preflight_validation_methods(
                        dataset,
                        methods=methods,
                        **settings,
                    )
                )

            preflight = pd.concat(
                preflight_frames,
                ignore_index=True,
            )
            failures = preflight[
                preflight["Status"]
                != "Pass"
            ]
            passed = failures.empty

            st.session_state[
                "soil_mir_preflight_table"
            ] = preflight
            st.session_state[
                "soil_mir_preflight_datasets"
            ] = datasets
            st.session_state[
                "soil_mir_preflight_passed"
            ] = passed
            st.session_state[
                "soil_mir_preflight_signature"
            ] = preflight_signature

            preflight_status.update(
                label=(
                    "Preflight passed"
                    if passed
                    else "Preflight failed"
                ),
                state=(
                    "complete"
                    if passed
                    else "error"
                ),
                expanded=not passed,
            )
    except Exception as exc:
        for key in (
            "soil_mir_preflight_table",
            "soil_mir_preflight_datasets",
            "soil_mir_preflight_passed",
            "soil_mir_preflight_signature",
        ):
            st.session_state.pop(
                key,
                None,
            )
        st.error(
            "Preflight could not be completed."
        )
        st.exception(exc)

preflight_exists = (
    st.session_state.get(
        "soil_mir_preflight_signature"
    )
    == preflight_signature
    and "soil_mir_preflight_table"
    in st.session_state
)
preflight_passed = bool(
    st.session_state.get(
        "soil_mir_preflight_passed",
        False,
    )
)

if preflight_exists:
    preflight_display = st.session_state[
        "soil_mir_preflight_table"
    ].copy()
    if "Method" in preflight_display.columns:
        preflight_display["Method"] = (
            preflight_display[
                "Method"
            ].map(
                validation_method_label
            )
        )
    st.dataframe(
        preflight_display,
        use_container_width=True,
        hide_index=True,
    )
    if preflight_passed:
        st.success(
            "Preflight passed. Review the table above, then start validation."
        )
    else:
        st.error(
            "Preflight failed. Validation is blocked until every selected "
            "property/method combination passes."
        )
else:
    st.info(
        "Run the preflight check before starting validation."
    )

st.subheader("2. Validation")
st.caption(
    "Start validation only after preflight passes. Progress reports the "
    "current property, validation method, outer split, and final all-data refit."
)

start_validation = st.button(
    "Start validation",
    type="primary",
    disabled=(
        not (
            preflight_exists
            and preflight_passed
        )
        or run_is_active
    ),
)

if start_validation:
    datasets = st.session_state.get(
        "soil_mir_preflight_datasets",
        {},
    )
    if set(datasets) != set(properties):
        st.error(
            "Preflight data are no longer available. Re-run preflight."
        )
        st.stop()

    job = start_validation_job(
        datasets=datasets,
        properties=properties,
        methods=methods,
        settings=dict(settings),
        spectra_dir=st.session_state[
            "soil_mir_spectra_dir"
        ],
        reference_excel=st.session_state[
            "soil_mir_reference_excel"
        ],
        output_dir=st.session_state[
            "soil_mir_output_dir"
        ],
        reference_ranges=dict(
            reference_ranges
        ),
        fallback_exclude_co2=bool(
            st.session_state.get(
                "soil_mir_exclude_co2",
                False,
            )
        ),
        resume_run_dir=(
            resume_run_dir_text
            or None
        ),
    )
    st.session_state[
        "soil_mir_active_validation_job"
    ] = job
    st.session_state[
        "soil_mir_background_progress"
    ] = 0.0
    st.session_state[
        "soil_mir_background_message"
    ] = "Validation queued."
    st.session_state[
        "soil_mir_background_log"
    ] = []
    st.session_state.pop(
        "soil_mir_last_run_outcome",
        None,
    )
    st.rerun()


@st.fragment(run_every=1.0)
def render_active_validation():
    job = st.session_state.get(
        "soil_mir_active_validation_job"
    )
    if job is None:
        return

    events = job.drain_events()
    if events:
        log = st.session_state.setdefault(
            "soil_mir_background_log",
            [],
        )
        for event in events:
            st.session_state[
                "soil_mir_background_progress"
            ] = event.get(
                "progress",
                0.0,
            )
            st.session_state[
                "soil_mir_background_message"
            ] = event.get(
                "message",
                "",
            )
            log.append(
                event.get(
                    "message",
                    "",
                )
            )
        if len(log) > 20:
            del log[:-20]

    st.markdown("### Active validation")
    st.progress(
        float(
            st.session_state.get(
                "soil_mir_background_progress",
                0.0,
            )
        )
    )
    st.write(
        st.session_state.get(
            "soil_mir_background_message",
            "Running...",
        )
    )

    if job.cancel_requested:
        st.warning(
            "Cancellation requested. The current safe unit of work "
            "will finish, then the run will stop and remain resumable."
        )
    else:
        if st.button(
            "Cancel validation",
            key="cancel_active_validation",
            type="secondary",
        ):
            job.request_cancel()
            st.session_state[
                "soil_mir_background_message"
            ] = (
                "Cancellation requested; waiting for a safe checkpoint."
            )
            st.rerun()

    with st.expander(
        "Recent run messages",
        expanded=False,
    ):
        for message in st.session_state.get(
            "soil_mir_background_log",
            [],
        ):
            st.write(message)

    if not job.future.done():
        return

    try:
        outcome = job.future.result()
    except Exception as exc:
        st.session_state[
            "soil_mir_last_run_outcome"
        ] = {
            "status": "failed",
            "message": str(exc),
            "run_dir": "",
            "pending": [],
        }
    else:
        results = outcome.get(
            "results",
            {},
        )
        if results:
            st.session_state[
                "soil_mir_results"
            ] = results
        run_dir = outcome.get(
            "run_dir",
            "",
        )
        comparison = outcome.get(
            "comparison_path",
            "",
        )
        if run_dir:
            st.session_state[
                "soil_mir_last_run_dir"
            ] = run_dir
        st.session_state[
            "soil_mir_last_comparison"
        ] = comparison

        pending = outcome.get(
            "pending",
            [],
        )
        status = outcome.get(
            "status",
            "",
        )
        if (
            run_dir
            and (
                pending
                or status
                in (
                    "cancelled",
                    "completed_with_errors",
                )
            )
        ):
            st.session_state[
                "soil_mir_resume_run_dir"
            ] = run_dir
        elif status == "completed":
            st.session_state.pop(
                "soil_mir_resume_run_dir",
                None,
            )

        st.session_state[
            "soil_mir_last_run_outcome"
        ] = {
            "status": status,
            "message": outcome.get(
                "message",
                "",
            ),
            "run_dir": run_dir,
            "pending": list(
                pending
            ),
        }

    st.session_state.pop(
        "soil_mir_active_validation_job",
        None,
    )
    st.session_state.pop(
        "soil_mir_background_progress",
        None,
    )
    st.session_state.pop(
        "soil_mir_background_message",
        None,
    )
    st.rerun()


render_active_validation()

last_outcome = st.session_state.get(
    "soil_mir_last_run_outcome"
)
if last_outcome:
    status = last_outcome.get(
        "status",
        "",
    )
    message = last_outcome.get(
        "message",
        "",
    )
    run_dir = last_outcome.get(
        "run_dir",
        "",
    )
    pending = last_outcome.get(
        "pending",
        [],
    )

    if status == "completed":
        st.success(
            (
                f"{message} Saved to {run_dir}."
                if run_dir
                else message
            )
        )
    elif status == "cancelled":
        st.warning(
            "Validation cancelled safely. "
            f"{len(pending)} analysis combination(s) remain pending. "
            "Resume this run from Run History."
        )
        if run_dir:
            st.write(
                f"Saved run: {run_dir}"
            )
    elif status == "completed_with_errors":
        st.warning(
            (
                f"{message} "
                "Successful results were preserved and the run can be resumed."
            )
        )
    elif status == "failed":
        st.error(
            f"Validation failed: {message}"
        )
