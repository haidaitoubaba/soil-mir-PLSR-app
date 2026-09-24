from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from soil_mir.plotting import (
    measured_vs_predicted_figure,
    residual_distribution_figure,
    residual_figure,
)
from soil_mir.services.history import (
    list_saved_models,
)
from soil_mir.services.local_paths import (
    choose_local_path,
    load_path_preferences,
)
from soil_mir.services.prediction import (
    predict_opus_directory,
    save_prediction_results,
)

st.set_page_config(
    page_title="Predict | Soil MIR PLSR",
    page_icon="🌱",
    layout="wide",
)
st.title("Predict")
st.caption(
    "Apply a saved final model to external local OPUS spectra. "
    "Prediction behavior follows predict_external_with_plsr_model.py."
)


def _safe_name(value: str) -> str:
    cleaned = "".join(
        char
        if char.isalnum() or char in ("-", "_")
        else "_"
        for char in value.strip()
    )
    return cleaned.strip("_") or "prediction"


preferences = load_path_preferences()

model_history_root = st.session_state.get(
    "soil_mir_output_dir",
    preferences.get(
        "output_dir",
        "",
    ),
)
historical_models = (
    list_saved_models(
        model_history_root
    )
    if model_history_root
    else []
)

if "soil_mir_predict_model_input" not in st.session_state:
    st.session_state[
        "soil_mir_predict_model_input"
    ] = ""
if "soil_mir_predict_spectra_input" not in st.session_state:
    st.session_state[
        "soil_mir_predict_spectra_input"
    ] = ""
if "soil_mir_predict_reference_input" not in st.session_state:
    st.session_state[
        "soil_mir_predict_reference_input"
    ] = preferences.get(
        "reference_excel",
        "",
    )
if "soil_mir_predict_output_input" not in st.session_state:
    st.session_state[
        "soil_mir_predict_output_input"
    ] = st.session_state.get(
        "soil_mir_output_dir",
        preferences.get("output_dir", ""),
    )

selected_history_model = st.session_state.get(
    "soil_mir_predict_selected_history_model"
)
if selected_history_model:
    st.success(
        "Model selected from Run History: "
        f"{selected_history_model.get('property', '')} / "
        f"{selected_history_model.get('method', '')} "
        f"({selected_history_model.get('run_id', '')})"
    )

if historical_models:
    model_options = {
        item["label"]: item["path"]
        for item in historical_models
    }
    selected_model_label = st.selectbox(
        "Saved final model",
        [""] + list(model_options),
        format_func=lambda value: (
            "Choose a model from Run History"
            if not value
            else value
        ),
        help=(
            "Models are listed newest first from the current Results "
            "directory. Selecting one does not modify the saved run."
        ),
    )
    if (
        selected_model_label
        and st.button(
            "Use selected saved model",
            key="use_saved_history_model",
        )
    ):
        st.session_state[
            "soil_mir_predict_model_input"
        ] = model_options[
            selected_model_label
        ]
        selected_item = next(
            item
            for item in historical_models
            if item["label"] == selected_model_label
        )
        st.session_state[
            "soil_mir_predict_selected_history_model"
        ] = {
            "run_id": selected_item.get(
                "run_id",
                "",
            ),
            "property": selected_item.get(
                "property",
                "",
            ),
            "method": selected_item.get(
                "method",
                "",
            ),
            "path": selected_item.get(
                "path",
                "",
            ),
        }
        st.rerun()
else:
    st.caption(
        "No saved final models were found in the current Results directory. "
        "You can still browse to any compatible .joblib model."
    )

model_col, model_browse_col = st.columns([5, 1])
with model_browse_col:
    if st.button(
        "Browse…",
        key="browse_predict_model",
        use_container_width=True,
    ):
        try:
            selected = choose_local_path(
                "file",
                prompt="Choose Final_Model.joblib",
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            if selected is not None:
                st.session_state[
                    "soil_mir_predict_model_input"
                ] = str(selected)
                st.session_state.pop(
                    "soil_mir_predict_selected_history_model",
                    None,
                )
with model_col:
    model_path = st.text_input(
        "Model bundle (.joblib)",
        key="soil_mir_predict_model_input",
        placeholder="/path/to/Final_Model.joblib",
    )

spectra_col, spectra_browse_col = st.columns([5, 1])
with spectra_browse_col:
    if st.button(
        "Browse…",
        key="browse_predict_spectra",
        use_container_width=True,
    ):
        try:
            selected = choose_local_path(
                "directory",
                prompt="Choose external OPUS spectra folder",
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            if selected is not None:
                st.session_state[
                    "soil_mir_predict_spectra_input"
                ] = str(selected)
with spectra_col:
    spectra_dir = st.text_input(
        "External OPUS spectra directory",
        key="soil_mir_predict_spectra_input",
        placeholder="/path/to/external/spectra",
    )

mode = st.radio(
    "Prediction mode",
    [
        "External validation",
        "Prediction only",
    ],
    horizontal=True,
    help=(
        "External validation uses a reference worksheet for exact "
        "File Name → Sample mapping and validation metrics. "
        "Prediction only treats each OPUS file as its own sample."
    ),
)

reference = None
reference_sheet = ""
if mode == "External validation":
    reference_col, reference_browse_col = st.columns(
        [5, 1]
    )
    with reference_browse_col:
        if st.button(
            "Browse…",
            key="browse_predict_reference",
            use_container_width=True,
        ):
            try:
                selected = choose_local_path(
                    "file",
                    prompt="Choose external reference workbook",
                )
            except Exception as exc:
                st.error(str(exc))
            else:
                if selected is not None:
                    st.session_state[
                        "soil_mir_predict_reference_input"
                    ] = str(selected)
    with reference_col:
        reference_excel = st.text_input(
            "Reference workbook",
            key="soil_mir_predict_reference_input",
            placeholder="/path/to/reference.xlsx",
        )

    sheet_options = []
    if reference_excel:
        try:
            excel_path = Path(
                reference_excel
            ).expanduser()
            if excel_path.is_file():
                sheet_options = [
                    name
                    for name in pd.ExcelFile(
                        excel_path
                    ).sheet_names
                    if name != "Property Metadata"
                ]
        except Exception as exc:
            st.warning(
                "Reference workbook could not be inspected yet: "
                f"{exc}"
            )

    if sheet_options:
        reference_sheet = st.selectbox(
            "Reference sheet",
            sheet_options,
        )
    else:
        reference_sheet = st.text_input(
            "Reference sheet",
            value="",
            placeholder="e.g. 213_STC",
        )

output_col, output_browse_col = st.columns([5, 1])
with output_browse_col:
    if st.button(
        "Browse…",
        key="browse_predict_output",
        use_container_width=True,
    ):
        try:
            selected = choose_local_path(
                "directory",
                prompt="Choose prediction results folder",
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            if selected is not None:
                st.session_state[
                    "soil_mir_predict_output_input"
                ] = str(selected)
with output_col:
    output_dir = st.text_input(
        "Prediction results directory",
        key="soil_mir_predict_output_input",
        placeholder="/path/to/results",
    )

max_extrapolation = st.number_input(
    "Maximum endpoint extrapolation (cm⁻¹)",
    min_value=0.0,
    value=0.25,
    step=0.05,
    format="%.2f",
    help=(
        "Matches the external prediction script. Only tiny model-grid "
        "boundary differences up to this limit are linearly extrapolated."
    ),
)

if st.button(
    "Run prediction",
    type="primary",
):
    if not model_path or not spectra_dir or not output_dir:
        st.error(
            "Select a model, external spectra folder, "
            "and prediction results directory."
        )
    elif (
        mode == "External validation"
        and (
            not st.session_state.get(
                "soil_mir_predict_reference_input"
            )
            or not reference_sheet
        )
    ):
        st.error(
            "External validation requires a reference workbook "
            "and reference sheet."
        )
    else:
        try:
            if mode == "External validation":
                reference = pd.read_excel(
                    Path(
                        st.session_state[
                            "soil_mir_predict_reference_input"
                        ]
                    ).expanduser(),
                    sheet_name=reference_sheet,
                )

            output_root = Path(
                output_dir
            ).expanduser()
            output_root.mkdir(
                parents=True,
                exist_ok=True,
            )
            cache_root = (
                output_root
                / ".soil_mir_cache"
            )

            with st.status(
                "Running external prediction",
                expanded=True,
            ) as status:
                result = predict_opus_directory(
                    Path(model_path).expanduser(),
                    Path(spectra_dir).expanduser(),
                    reference=reference,
                    max_extrapolation_cm1=(
                        float(max_extrapolation)
                    ),
                    cache_root=cache_root,
                )

                bundle = result["bundle"]
                property_name = str(
                    bundle.get(
                        "property_name",
                        "prediction",
                    )
                )
                timestamp = datetime.now().strftime(
                    "%Y%m%d_%H%M%S"
                )
                workbook_path = (
                    output_root
                    / "predictions"
                    / (
                        f"{timestamp}_"
                        f"{_safe_name(property_name)}_"
                        "predictions.xlsx"
                    )
                )
                save_prediction_results(
                    result["file_predictions"],
                    result["sample_predictions"],
                    result["metrics"],
                    bundle,
                    workbook_path,
                    model_path,
                    (
                        reference_sheet
                        if mode
                        == "External validation"
                        else ""
                    ),
                )
                result["workbook_path"] = (
                    workbook_path
                )
                result["mode"] = mode
                result["reference_sheet"] = (
                    reference_sheet
                )
                result["max_extrapolation_cm1"] = (
                    float(max_extrapolation)
                )
                st.session_state[
                    "soil_mir_prediction_result"
                ] = result
                status.update(
                    label="Prediction complete",
                    state="complete",
                    expanded=False,
                )
        except Exception as exc:
            st.error("Prediction failed.")
            st.exception(exc)

result = st.session_state.get(
    "soil_mir_prediction_result"
)
if result:
    bundle = result["bundle"]
    st.success("Prediction complete.")

    st.subheader("Model")
    model_a, model_b, model_c, model_d = st.columns(4)
    model_a.metric(
        "Property",
        bundle.get("property_name", ""),
    )
    model_b.metric(
        "PLS rank",
        bundle.get("selected_rank", ""),
    )
    model_c.metric(
        "Preprocessing",
        bundle.get(
            "selected_preprocessing",
            "",
        ),
    )
    model_d.metric(
        "Transform",
        bundle.get(
            "response_transform",
            "",
        ),
    )
    st.caption(
        "Maximum endpoint extrapolation: "
        f"{result.get('max_extrapolation_cm1', 0.25):.2f} cm⁻¹"
    )

    metrics = result.get("metrics", {})
    sample_predictions = result[
        "sample_predictions"
    ]
    file_predictions = result[
        "file_predictions"
    ]

    if (
        result.get("mode")
        == "External validation"
        and "Measured" in sample_predictions.columns
    ):
        st.subheader("External validation")
        metric_cols = st.columns(6)
        for column, key in zip(
            metric_cols,
            [
                "R2",
                "RMSE",
                "RPIQ",
                "Bias",
                "Samples",
                "Spectra",
            ],
        ):
            value = metrics.get(key, "")
            if isinstance(value, float):
                column.metric(
                    key,
                    f"{value:.4g}",
                )
            else:
                column.metric(key, value)

        chart_frame = sample_predictions[
            ["Measured", "Predicted"]
        ].copy()
        st.subheader(
            "Measured vs predicted"
        )
        prediction_plot = (
            measured_vs_predicted_figure(
                chart_frame["Measured"],
                chart_frame["Predicted"],
                title=(
                    f"{bundle.get('property_name', '')} "
                    "— external validation"
                ),
                predicted_label="Predicted",
            )
        )
        st.pyplot(
            prediction_plot,
            clear_figure=True,
            use_container_width=False,
        )


        external_residual = (
            chart_frame["Measured"]
            - chart_frame["Predicted"]
        )
        st.subheader(
            "Residuals"
        )
        external_residual_plot = residual_figure(
            chart_frame["Predicted"],
            external_residual,
            title=(
                f"{bundle.get('property_name', '')} "
                "— external validation residuals"
            ),
            predicted_label="Predicted",
        )
        st.pyplot(
            external_residual_plot,
            clear_figure=True,
            use_container_width=False,
        )

        st.subheader(
            "Residual distribution"
        )
        external_residual_histogram = (
            residual_distribution_figure(
                external_residual,
                title=(
                    f"{bundle.get('property_name', '')} "
                    "— external validation residual distribution"
                ),
            )
        )
        st.pyplot(
            external_residual_histogram,
            clear_figure=True,
            use_container_width=False,
        )

    st.subheader("Sample predictions")
    st.dataframe(
        sample_predictions,
        use_container_width=True,
        hide_index=True,
    )

    with st.expander(
        "Individual spectrum predictions"
    ):
        st.dataframe(
            file_predictions,
            use_container_width=True,
            hide_index=True,
        )

    workbook_path = result.get(
        "workbook_path"
    )
    if workbook_path:
        workbook_path = Path(workbook_path)
        if workbook_path.is_file():
            st.write(
                "Saved workbook: "
                f"{workbook_path}"
            )
            st.download_button(
                "Download prediction results Excel",
                data=workbook_path.read_bytes(),
                file_name=workbook_path.name,
                mime=(
                    "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet"
                ),
            )

    st.download_button(
        "Download sample predictions CSV",
        data=sample_predictions.to_csv(
            index=False
        ).encode("utf-8"),
        file_name="sample_predictions.csv",
        mime="text/csv",
    )
