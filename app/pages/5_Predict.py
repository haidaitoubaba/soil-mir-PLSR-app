from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from soil_mir.io.opus import OPUS_LEGACY, OPUS_NATIVE, list_opus_files
from soil_mir.services.model_catalog import list_model_catalog, model_file_identity
from soil_mir.ui_models import render_model_preview, select_catalog_model
from soil_mir.ui_state import remember_widget, request_section, reset_remembered, section_navigation

from soil_mir.plotting import (
    measured_vs_predicted_figure,
    residual_distribution_figure,
    residual_figure,
)
from soil_mir.services.local_paths import (
    choose_local_path,
    load_path_preferences,
    open_local_folder,
)
from soil_mir.services.prediction import (
    PredictionCompatibilityError,
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
    "Apply a saved final model to external local OPUS spectra."
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

state = st.session_state
section = section_navigation("predict")
for key, value in {
    "soil_mir_predict_model_input": "",
    "soil_mir_predict_spectra_input": "",
    "soil_mir_predict_reference_input": preferences.get("reference_excel", ""),
    "soil_mir_predict_output_input": state.get(
        "soil_mir_output_dir", preferences.get("output_dir", "")
    ),
}.items():
    state.setdefault(key, value)


def invalidate_compatibility():
    state.pop("soil_mir_prediction_compatibility", None)
    state.pop("rc6_predict_confirmation", None)
    state.rc6_predict_confirmation_epoch = state.get("rc6_predict_confirmation_epoch", 0) + 1


def clear_model():
    if state.get("soil_mir_predict_model_input") or state.get("rc6_predict_model_identity"):
        invalidate_compatibility()
    state.soil_mir_predict_model_input = ""
    state.pop("soil_mir_predict_selected_history_model", None)
    state.pop("rc6_predict_model_identity", None)


def apply_model(path, entry=None):
    signature = model_file_identity(path)
    active = (signature, entry.get("id") if entry else None)
    if state.get("rc6_predict_model_identity") != active:
        invalidate_compatibility()
    state.rc6_predict_model_identity = active
    state.soil_mir_predict_model_input = signature[0]
    if entry:
        state.soil_mir_predict_selected_history_model = dict(entry)
    else:
        state.pop("soil_mir_predict_selected_history_model", None)


def path_widget(label, key, *, kind, prompt, placeholder):
    text_col, browse_col = st.columns([5, 1])
    if browse_col.button("Browse…", key=f"browse_{key}", use_container_width=True):
        try:
            path = choose_local_path(kind, prompt=prompt)
            if path is not None:
                state[key] = str(path)
        except Exception as exc:
            st.error(str(exc))
    widget = f"_rc6_predict_path_{key}"
    if widget not in state or state[widget] != state.get(key, ""):
        state[widget] = state.get(key, "")

    def store():
        state[key] = state[widget]

    result = text_col.text_input(label, key=widget, placeholder=placeholder, on_change=store)
    state[key] = result
    return result


def fingerprint(path):
    resolved = Path(path).expanduser().resolve()
    stat = resolved.stat()
    if not resolved.is_file():
        raise ValueError(f"File not found: {resolved}")
    return str(resolved), stat.st_size, stat.st_mtime_ns


def active_model_available():
    path = state.get("soil_mir_predict_model_input")
    active = state.get("rc6_predict_model_identity")
    if not path or not active:
        return False
    try:
        return model_file_identity(path) == active[0]
    except (OSError, ValueError):
        return False


if section == "Model":
    incoming = state.pop("rc6_predict_incoming", False)
    old_record = state.get("soil_mir_predict_selected_history_model")
    old_path = state.get("soil_mir_predict_model_input", "")
    if incoming or (old_record and old_path and not state.get("rc6_predict_model_identity")):
        reset_remembered("predict_source", "Run History")
        if state.get("rc6_predict_root"):
            state.rc6_predict_root_input = state.rc6_predict_root
        incoming = True
    if state.pop("rc6_predict_selection_removed", False):
        st.warning("The selected saved model was removed. Select another model explicitly.")
    if state.get("rc6_predict_model_identity") and not active_model_available():
        clear_model()
        st.warning("The model file changed or is missing. Preview and select it again.")
    source = remember_widget(
        st, "radio", "Model source", key="predict_source",
        options=["Run History", "Browse model file"], horizontal=True,
    )
    if source == "Run History":
        state.setdefault("rc6_predict_root_input", state.get("rc6_predict_root") or state.get(
            "rc6_history_root") or state.get(
                "soil_mir_output_dir", preferences.get("output_dir", "")))
        root_text = path_widget(
            "Model library / Results directory", "rc6_predict_root_input",
            kind="directory", prompt="Choose model library", placeholder="/path/to/results",
        )
        root = str(Path(root_text).expanduser().resolve()) if root_text.strip() else ""
        state.rc6_predict_root = root
        entries = list_model_catalog(root)
        preferred = None
        if incoming and old_record and old_path:
            target = str(Path(old_path).expanduser().resolve())
            matches = [item for item in entries if item["path"] == target
                       and item["run_id"] == old_record.get("run_id")
                       and item["property"] == old_record.get("property")
                       and item["method"] == old_record.get("method")
                       and (not old_record.get("model_role")
                            or item["model_role"] == old_record["model_role"])]
            if old_record.get("id"):
                matches = [item for item in matches if item["id"] == old_record["id"]]
            if len(matches) == 1:
                preferred = matches[0]
            else:
                clear_model()
                st.warning("The exact model from the other page is unavailable in this library.")
        prefix = "predict_catalog_" + hashlib.sha256(root.encode()).hexdigest()[:16]
        candidate = select_catalog_model(entries, prefix, preferred=preferred)
        active = state.get("rc6_predict_model_identity")
        if candidate is None or (active and active[1] != candidate["id"]):
            clear_model()
        if candidate is not None:
            if candidate.get("alias_error"):
                st.warning(f"Run name unavailable: {candidate['alias_error']}")
            st.caption(f"Selected artifact: {candidate['path']}")
            already_applied = bool(active_model_available() and state.get(
                "rc6_predict_model_identity", (None, None))[1] == candidate["id"])
            preview = render_model_preview(
                candidate["path"], candidate, "rc6_predict_preview",
                automatic=already_applied or preferred is not None,
            )
            if preview is not None and (
                preferred is not None or st.button("Use selected saved model")
            ):
                apply_model(candidate["path"], candidate)
            elif already_applied and preview is not None:
                # Alias updates are display-only and do not change the selected artifact.
                state.soil_mir_predict_selected_history_model = dict(candidate)
    else:
        state.setdefault("rc6_predict_manual_path", old_path if not old_record else "")
        path = path_widget(
            "Model bundle (.joblib)", "rc6_predict_manual_path", kind="file",
            prompt="Choose a trusted saved model", placeholder="/path/to/Final_Model.joblib",
        )
        active = state.get("rc6_predict_model_identity")
        expected_path = str(Path(path).expanduser().resolve()) if path.strip() else ""
        if active and (active[1] is not None or active[0][0] != expected_path):
            clear_model()
        if not path.strip():
            clear_model()
        else:
            already_applied = active_model_available() and state.get(
                "rc6_predict_model_identity", (None, None))[1] is None
            preview = render_model_preview(path, None, "rc6_predict_preview",
                                           automatic=already_applied)
            if preview is not None and st.button("Use selected model file"):
                apply_model(path)
    if active_model_available():
        st.success(f"Active model: {state.soil_mir_predict_model_input}")
        if st.button("Continue to Input Data"):
            request_section("predict", "Input Data")
            st.rerun()
    else:
        st.info("Preview and confirm an available model before prediction.")
    st.stop()

if not active_model_available() and section != "Results":
    clear_model()
    st.warning("Select and confirm an available model in Model first.")
    st.stop()

model_path = state.get("soil_mir_predict_model_input", "")
history_model = state.get("soil_mir_predict_selected_history_model") or {}
if model_path:
    st.caption(f"Model: {history_model.get('run_label') or model_path} | "
               f"{history_model.get('property', '')} / {history_model.get('variant', '')}")

if section == "Input Data":
    spectra_dir = path_widget(
        "External OPUS spectra directory", "soil_mir_predict_spectra_input",
        kind="directory", prompt="Choose external OPUS spectra folder",
        placeholder="/path/to/external/spectra",
    )
    mode = remember_widget(
        st, "radio", "Prediction mode", key="predict_mode",
        options=["External validation", "Prediction only"], horizontal=True,
        help="External validation uses exact File Name → Sample mapping and measured values. "
             "Prediction only treats each OPUS file as its own sample.",
    )
    reference_excel, reference_sheet = "", ""
    if mode == "External validation":
        reference_excel = path_widget(
            "Reference workbook", "soil_mir_predict_reference_input",
            kind="file", prompt="Choose external reference workbook",
            placeholder="/path/to/reference.xlsx",
        )
        sheet_options = []
        if reference_excel:
            try:
                with pd.ExcelFile(Path(reference_excel).expanduser()) as book:
                    sheet_options = [name for name in book.sheet_names
                                     if name != "Property Metadata"]
            except Exception as exc:
                st.warning(f"Reference workbook could not be inspected: {exc}")
        if sheet_options:
            reference_sheet = remember_widget(
                st, "selectbox", "Reference sheet", key="predict_reference_sheet",
                options=[""] + sheet_options,
                format_func=lambda name: name or "Choose reference sheet",
            )
        else:
            reference_sheet = remember_widget(
                st, "text_input", "Reference sheet", key="predict_reference_sheet",
                placeholder="e.g. TC",
            )
    axis_mode = remember_widget(
        st, "selectbox", "OPUS wavenumber axis", key="predict_axis_mode",
        options=(None, OPUS_NATIVE, OPUS_LEGACY),
        format_func={None: "Match saved model", OPUS_NATIVE: "Declared valid points (NPT)",
                     OPUS_LEGACY: "Legacy array length"}.get,
        help="Models saved before native-axis support use the legacy reader in automatic mode.",
    )
    crop_enabled = remember_widget(st, "checkbox", "Crop input spectra", key="predict_crop")
    crop_min = crop_max = None
    if crop_enabled:
        st.caption("Leave either bound blank to keep that end. Between measured points, the crop "
                   "boundary is projected from the two retained points nearest that end.")
        lower_col, upper_col = st.columns(2)
        crop_min = remember_widget(
            lower_col, "number_input", "Crop minimum (cm⁻¹)", key="predict_crop_min",
            min_value=0.0, value=None, step=0.01, format="%.4f",
        )
        crop_max = remember_widget(
            upper_col, "number_input", "Crop maximum (cm⁻¹)", key="predict_crop_max",
            min_value=0.0, value=None, step=0.01, format="%.4f",
        )
    inputs = (spectra_dir, mode, reference_excel, reference_sheet, axis_mode, crop_min, crop_max)
    if state.get("rc6_predict_inputs") != inputs:
        invalidate_compatibility()
        state.rc6_predict_inputs = inputs
    if st.button("Continue to Compatibility"):
        request_section("predict", "Compatibility")
        st.rerun()
    st.stop()

inputs = state.get("rc6_predict_inputs")
if inputs:
    spectra_dir, mode, reference_excel, reference_sheet, axis_mode, crop_min, crop_max = inputs
else:
    spectra_dir, mode, reference_excel, reference_sheet = "", "External validation", "", ""
    axis_mode = crop_min = crop_max = None

if section == "Compatibility":
    extrapolation_mode = remember_widget(
        st, "radio", "Endpoint extrapolation mode", key="predict_extrapolation_mode",
        options=["Automatic", "Manual"], horizontal=True,
    )
    max_extrapolation, automatic_limit = 0.25, 10.0
    if extrapolation_mode == "Automatic":
        automatic_limit = remember_widget(
            st, "number_input", "Automatic extrapolation safety limit (cm⁻¹)",
            key="predict_automatic_limit", min_value=0.0, value=10.0, step=0.25, format="%.2f",
        )
        st.caption("Software guardrail, not a scientifically validated safe limit.")
    else:
        max_extrapolation = remember_widget(
            st, "number_input", "Maximum endpoint extrapolation (cm⁻¹)",
            key="predict_manual_limit", min_value=0.0, value=0.25, step=0.05, format="%.2f",
        )
    limits = (extrapolation_mode, max_extrapolation, automatic_limit)
    if state.get("rc6_predict_limits") != limits:
        invalidate_compatibility()
        state.rc6_predict_limits = limits
else:
    limits = state.get("rc6_predict_limits", ("Automatic", 0.25, 10.0))
    extrapolation_mode, max_extrapolation, automatic_limit = limits

output_dir = state.get("soil_mir_predict_output_input", "")
if section == "Prediction":
    output_dir = path_widget(
        "Prediction results directory", "soil_mir_predict_output_input",
        kind="directory", prompt="Choose prediction results folder",
        placeholder="/path/to/results",
    )


def input_identity():
    if not active_model_available() or not spectra_dir.strip():
        raise ValueError("Select a model and external spectra directory.")
    directory = Path(spectra_dir).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"External spectra folder not found: {directory}")
    reference = None
    reference_id = None
    if mode == "External validation":
        if not reference_excel or not reference_sheet:
            raise ValueError("External validation requires a reference workbook and sheet.")
        reference_id = (fingerprint(reference_excel), reference_sheet)
        cached = state.get("rc6_predict_reference_frame")
        if not cached or cached[0] != reference_id:
            frame = pd.read_excel(Path(reference_excel).expanduser(), sheet_name=reference_sheet)
            state.rc6_predict_reference_frame = (reference_id, frame)
        reference = state.rc6_predict_reference_frame[1]
        if "File Name" not in reference.columns:
            raise ValueError("Reference sheet is missing the File Name column.")
        names = list(dict.fromkeys(str(value).strip() for value in reference["File Name"]
                                  if str(value).strip()))
        paths = [directory / name for name in names]
    else:
        paths = list_opus_files(directory)
        if not paths:
            paths = sorted(p for p in directory.iterdir()
                           if p.is_file() and not p.name.startswith("."))
    if not paths:
        raise ValueError("No external spectra files were found.")
    inventory = tuple(fingerprint(path) for path in paths)
    identity = (state.rc6_predict_model_identity, str(directory), inventory, mode,
                reference_id, axis_mode, crop_min, crop_max, limits)
    digest = hashlib.sha256(json.dumps(identity, default=str).encode()).hexdigest()
    return digest, reference


config_id, reference = None, None
try:
    config_id, reference = input_identity()
except Exception as exc:
    if section != "Results":
        st.warning(str(exc))
    invalidate_compatibility()

saved_check = state.get("soil_mir_prediction_compatibility")
if saved_check and saved_check.get("config_id") != config_id:
    invalidate_compatibility()
    saved_check = None
report = saved_check["report"] if saved_check else None
confirmed_signature = None
if report and state.get("rc6_predict_confirmation") == (config_id, report["signature"]):
    confirmed_signature = report["signature"]

if section == "Compatibility":
    st.subheader("Spectral compatibility check")
    st.caption("Checks actual aligned coverage against the saved model grid. "
               "Interpolation does not correct instrument transfer bias.")
    if report:
        st.dataframe(pd.DataFrame([(key, str(value)) for key, value in report["metadata"].items()],
                                  columns=["Check", "Value"]), hide_index=True)
        with st.expander("Per-file native coverage and limiting files"):
            st.dataframe(pd.DataFrame(report["files"]), hide_index=True)
        if report["compatible"]:
            st.success(report["reason"])
            if report["requires_confirmation"]:
                st.warning("Extrapolation exceeds 0.25 cm⁻¹. Validate the impact on predictions.")
                epoch = state.get("rc6_predict_confirmation_epoch", 0)
                confirm_key = f"predict_confirm_{epoch}_{config_id}_{report['signature']}"
                if confirm_key not in state:
                    state[confirm_key] = confirmed_signature is not None

                def store_confirmation():
                    if state[confirm_key]:
                        state.rc6_predict_confirmation = (config_id, report["signature"])
                    else:
                        state.pop("rc6_predict_confirmation", None)

                confirmed = st.checkbox(
                    "Confirm calculated endpoint extrapolation", key=confirm_key,
                    on_change=store_confirmation,
                )
                confirmed_signature = report["signature"] if confirmed else None
                if confirmed:
                    state.rc6_predict_confirmation = (config_id, report["signature"])
                else:
                    state.pop("rc6_predict_confirmation", None)
        else:
            st.error(report["reason"] + " Review ranges or retrain on shared coverage.")
    check = st.button("Check spectral compatibility", disabled=not config_id)
    if report and report["compatible"] and (
        not report["requires_confirmation"] or confirmed_signature
    ):
        if st.button("Continue to Prediction"):
            request_section("predict", "Prediction")
            st.rerun()
    run = False
elif section == "Prediction":
    st.subheader("Prediction configuration")
    st.caption(f"External data: {spectra_dir} | {mode} | "
               f"Reference: {reference_sheet or 'Not used'}")
    st.caption(f"OPUS axis: {axis_mode or 'Match saved model'} | Crop: {crop_min}–{crop_max}")
    st.caption(f"Endpoint mode: {extrapolation_mode} | Output: {output_dir}")
    blocked = bool(report and (
        not report["compatible"] or (report["requires_confirmation"] and not confirmed_signature)
    ))
    if blocked:
        st.warning("Review and confirm the current compatibility report before prediction.")
        if st.button("Open Compatibility"):
            request_section("predict", "Compatibility")
            st.rerun()
    elif report:
        st.success(report["reason"])
    else:
        st.info("Prediction will perform compatibility preflight before calculating results.")
    check = False
    run = st.button("Run prediction", type="primary",
                    disabled=not config_id or not output_dir.strip() or blocked)
else:
    check = run = False

if check or run:
    # Recheck source identities immediately before execution.
    try:
        fresh_id, reference = input_identity()
        if fresh_id != config_id:
            invalidate_compatibility()
            raise ValueError("Input files changed. Repeat compatibility check.")
        if check:
            invalidate_compatibility()
            confirmed_signature = None
        output_root = Path(output_dir).expanduser() if output_dir.strip() else None
        cache_root = (output_root / ".soil_mir_cache" if output_root is not None
                      else Path.home() / ".soil_mir_app" / "prediction_cache")
        if run:
            output_root.mkdir(parents=True, exist_ok=True)
        with st.status("Checking coverage" if check else "Running external prediction",
                       expanded=True) as status:
            result = predict_opus_directory(
                Path(model_path).expanduser(), Path(spectra_dir).expanduser(),
                reference=reference, max_extrapolation_cm1=float(max_extrapolation),
                cache_root=cache_root, opus_axis_mode=axis_mode,
                crop_min_cm1=crop_min, crop_max_cm1=crop_max,
                extrapolation_mode=extrapolation_mode, automatic_limit_cm1=automatic_limit,
                inspect_only=check, require_confirmation=True,
                confirmed_signature=confirmed_signature,
            )
            if input_identity()[0] != config_id:
                raise ValueError(
                    "Input files changed during processing. Repeat compatibility check."
                )
            state.soil_mir_prediction_compatibility = {
                "config_id": config_id, "report": result["compatibility"],
            }
            if check:
                st.rerun()
            bundle = result["bundle"]
            property_name = str(bundle.get("property_name", "prediction"))
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            workbook_path = (output_root / "predictions"
                             / f"{timestamp}_{_safe_name(property_name)}_predictions.xlsx")
            save_prediction_results(
                result["file_predictions"], result["sample_predictions"], result["metrics"],
                bundle, workbook_path, model_path,
                reference_sheet if mode == "External validation" else "",
                input_metadata=result["input_metadata"], compatibility=result["compatibility"],
            )
            result.update({
                "workbook_path": workbook_path, "mode": mode, "reference_sheet": reference_sheet,
                "max_extrapolation_cm1": result["compatibility"]["tolerance"],
                "rc6_config_id": config_id, "rc6_model_path": model_path,
                "rc6_spectra_dir": spectra_dir, "rc6_reference_excel": reference_excel,
                "rc6_output_dir": output_dir, "rc6_model_label": history_model.get("run_label", ""),
                "rc6_created": timestamp,
            })
            state.soil_mir_prediction_result = result
            state.pop("rc6_predict_failed", None)
            status.update(label="Prediction complete", state="complete", expanded=False)
            request_section("predict", "Results")
            st.rerun()
    except PredictionCompatibilityError as exc:
        invalidate_compatibility()
        state.soil_mir_prediction_compatibility = {"config_id": config_id, "report": exc.report}
        state.rc6_predict_failed = config_id
        request_section("predict", "Compatibility")
        st.rerun()
    except Exception as exc:
        invalidate_compatibility()
        state.rc6_predict_failed = config_id
        st.error("Compatibility check failed." if check else "Prediction failed.")
        st.exception(exc)

if section == "Results":
    result = st.session_state.get(
        "soil_mir_prediction_result"
    )
    if result:
        bundle = result["bundle"]
        current = (config_id is not None and result.get("rc6_config_id") == config_id
                   and result.get("rc6_output_dir") == output_dir
                   and state.get("rc6_predict_failed") != config_id)
        if current:
            st.success("Prediction complete.")
        else:
            st.warning("Historical result — not a prediction for the current input settings.")
        st.caption(f"Source model: {result.get('rc6_model_path', 'Not recorded')} | "
                   f"External spectra: {result.get('rc6_spectra_dir', 'Not recorded')} | "
                   f"Reference sheet: {result.get('reference_sheet') or 'Not used'}")
        st.caption(f"Prediction run: {result.get('rc6_created', 'Not recorded')}")

        workbook_path = Path(
            result.get(
                "workbook_path",
                "",
            )
        ).expanduser()
        if (
            workbook_path
            and workbook_path.parent.is_dir()
        ):
            if st.button(
                "Open results folder",
                key="open_prediction_results_folder",
                type="secondary",
            ):
                try:
                    open_local_folder(
                        workbook_path.parent
                    )
                except Exception as exc:
                    st.error(
                        f"Could not open results folder: {exc}"
                    )

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

        input_metadata = result.get("input_metadata", {})
        if input_metadata:
            st.caption(
                f"OPUS axis: {input_metadata['Prediction OPUS axis mode']} · "
                f"Aligned range: {input_metadata['Aligned minimum (cm⁻¹)']:.4f}–"
                f"{input_metadata['Aligned maximum (cm⁻¹)']:.4f} cm⁻¹"
            )
            if (input_metadata.get("Prediction OPUS axis mode")
                    != input_metadata.get("Model OPUS axis mode")):
                st.info("Prediction used a different OPUS axis method from model calibration.")
        compatibility = result.get("compatibility")
        if compatibility:
            with st.expander("Saved compatibility and extrapolation details"):
                st.dataframe(pd.DataFrame(
                    [(key, str(value)) for key, value in compatibility["metadata"].items()],
                    columns=["Check", "Value"],
                ), hide_index=True)
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
            metric_rows = (
                ("R2", "RMSE", "RPIQ", "Bias"),
                ("RPD", "MAE", "CCC", "Samples", "Spectra"),
            )
            for metric_row in metric_rows:
                for column, key in zip(
                    st.columns(len(metric_row)),
                    metric_row,
                ):
                    value = metrics.get(key, "")
                    label = "R²" if key == "R2" else key
                    if isinstance(value, float):
                        column.metric(
                            label,
                            f"{value:.4g}",
                        )
                    else:
                        column.metric(label, value)

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
    else:
        st.info("No completed prediction is available in this session.")
