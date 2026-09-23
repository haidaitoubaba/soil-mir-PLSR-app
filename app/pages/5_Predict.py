from __future__ import annotations

from pathlib import Path

import streamlit as st

from soil_mir.services.prediction import (
    predict_opus_directory,
)

st.set_page_config(
    page_title="Predict | Soil MIR PLSR",
    page_icon="🌱",
    layout="wide",
)
st.title("Predict")
st.caption(
    "Apply a saved final model to new local OPUS spectra."
)

saved_models = []
for result in st.session_state.get(
    "soil_mir_results",
    {},
).values():
    model = result.get(
        "artifacts",
        {},
    ).get("model")
    if model:
        saved_models.append(model)

if saved_models:
    selected_model = st.selectbox(
        "Recent model",
        saved_models,
    )
else:
    selected_model = ""

model_path = st.text_input(
    "Model bundle (.joblib)",
    value=selected_model,
    placeholder="/path/to/Final_Model.joblib",
)
spectra_dir = st.text_input(
    "New OPUS spectra directory",
    value="",
    placeholder="/path/to/new/spectra",
)

if st.button(
    "Predict",
    type="primary",
):
    try:
        result = predict_opus_directory(
            Path(model_path).expanduser(),
            Path(spectra_dir).expanduser(),
        )
    except Exception as exc:
        st.exception(exc)
    else:
        bundle = result["bundle"]
        st.success(
            "Prediction complete."
        )
        st.write(
            f"**Property:** {bundle.get('property_name', '')}"
        )
        st.write(
            f"**Units:** {bundle.get('units', '')}"
        )
        st.write(
            "**Model:** "
            f"{bundle.get('selected_preprocessing')} | "
            f"{bundle.get('selected_region')} | "
            f"rank {bundle.get('selected_rank')}"
        )

        st.subheader(
            "Sample-average predictions"
        )
        sample_predictions = result[
            "sample_predictions"
        ]
        st.dataframe(
            sample_predictions,
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "Download sample predictions CSV",
            data=sample_predictions.to_csv(
                index=False
            ).encode("utf-8"),
            file_name="sample_predictions.csv",
            mime="text/csv",
        )

        with st.expander(
            "Individual spectrum predictions"
        ):
            file_predictions = result[
                "file_predictions"
            ]
            st.dataframe(
                file_predictions,
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                "Download spectrum predictions CSV",
                data=file_predictions.to_csv(
                    index=False
                ).encode("utf-8"),
                file_name="spectrum_predictions.csv",
                mime="text/csv",
            )
