from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import hashlib
import io
import json

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from soil_mir.ui_navigation import tile_button
from soil_mir.ui_qc_source import (
    applied_directory, canonical_directory, choose_source, completed_batch, effective_directory,
    guard_source, invalidate_source, source_mode,
)
from soil_mir.ui_state import remember_widget, request_section, reset_remembered, section_navigation

from soil_mir.io.opus import list_opus_files
from soil_mir.qc import COMPARISON_METHODS, DECISION_STRATEGIES, Criteria, REGIONS, group_issues
from soil_mir.preprocessing import NO_SG_METHODS, PREPROCESSING_NAMES
from soil_mir.services.local_paths import choose_local_path, open_local_folder
from soil_mir.services.spectral_qc import (
    evaluate_batch, file_inventory, prepare_batch, preview_spectra, recommended_reviews,
    report_bytes,
)

from soil_mir.services.qc_manifest import (
    DECISION_ORDER, apply_review_edits, build_manifest, criteria_from_dict,
    decision_export_rows, export_decision_spectra, input_settings, read_mapping, resolve_groups,
    review_history_push, review_history_undo, review_selection, save_manifest, validate_manifest,
)

def set_review_state(updated, notice, *, history=None):
    """Commit a shared review transaction and invalidate stale frozen selections."""
    state = st.session_state
    if updated == state.qc_reviews:
        return False
    if history is None:
        history = review_history_push(
            state.qc_reviews, updated, state.get("qc_review_history", [])
        )
    state.qc_review_history = history
    state.qc_reviews = updated
    if state.pop("qc_frozen", None):
        notice += " Previous frozen selection is no longer current; freeze again if needed."
    state.qc_review_revision = state.get("qc_review_revision", 0) + 1
    state.qc_review_notice = notice
    return True


def save_review_edits(edits, file_table):
    try:
        updated = apply_review_edits(file_table, st.session_state.qc_reviews, edits)
    except ValueError as exc:
        st.error(str(exc))
        return
    if set_review_state(updated, "Review decisions saved and synchronized."):
        st.rerun()
    else:
        st.info("No review changes to save.")


def review_editor(frame, key, file_table):
    """All tables edit the same saved decisions; submit before switching views."""
    if frame.empty:
        st.dataframe(frame, hide_index=True)
        return
    frame = frame.copy().reset_index(drop=True)
    if "Manual reason" not in frame:
        reasons = file_table.set_index("File Name")["Manual reason"]
        frame["Manual reason"] = frame["File Name"].map(reasons).fillna("")
    revision = st.session_state.get("qc_review_revision", 0)
    identity = hashlib.sha256(
        json.dumps(frame["File Name"].tolist(), ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    with st.form(f"qc_editor_{key}_{revision}_{identity}"):
        edited = st.data_editor(
            frame, hide_index=True, num_rows="fixed",
            disabled=[c for c in frame.columns if c not in ("Manual decision", "Manual reason")],
            column_config={
                "Manual decision": st.column_config.SelectboxColumn(
                    "Manual decision", options=list(DECISION_ORDER), required=True
                ),
                "Manual reason": st.column_config.TextColumn("Reason (optional)"),
            },
            key=f"qc_table_{key}_{revision}_{identity}",
        )
        if st.form_submit_button("Save table decisions"):
            save_review_edits(edited.to_dict("records"), file_table)


st.title("Spectral QC")
st.caption("Standalone OPUS replicate consistency checks. No reference values required.")
st.info(
    "Use one measurement batch per folder. A consistency pass is not proof of chemical "
    "accuracy or correct sample identity. Original spectra are never changed."
)

section = section_navigation("qc")
if section == "Setup":
    # An invalid draft must not leave a previously valid setup masquerading as current.
    st.session_state.pop("rc6_qc_setup", None)

    state = st.session_state
    st.subheader("Spectral data source")
    a, b = st.columns(2)
    mode = source_mode(state)
    tile_button(a, "Linked to Modeling Data", "link", key="rc7_qc_linked",
                selected=mode == "linked", on_click=choose_source, args=(state, "linked"))
    tile_button(b, "Independent", "folder_open", key="rc7_qc_independent",
                selected=mode == "independent", on_click=choose_source, args=(state, "independent"))
    if mode == "linked":
        directory = applied_directory(state)
        st.text_input("OPUS spectra directory (linked)", value=directory, disabled=True)
        st.caption("QC uses the OPUS folder applied in Modeling Data.")
        if not directory or not Path(directory).is_dir():
            invalidate_source(state, "The linked Modeling Data directory is unavailable.")
            st.warning(
                "Inspect the directory again in Modeling Data or choose an independent folder."
            )
            st.stop()
    else:
        if not applied_directory(state):
            st.caption(
                "Use Independent to check an OPUS folder. Apply inputs in Modeling Data "
                "to link its OPUS directory."
            )
        a, b = st.columns([5, 1])
        if b.button("Browse", key="qc_browse"):
            try:
                chosen = choose_local_path("directory", prompt="Choose OPUS spectral QC folder")
                if chosen:
                    reset_remembered("qc_dir", str(chosen))
                    state.rc7_qc_source_mode = "independent"
            except RuntimeError as exc:
                st.warning(str(exc))
        directory = remember_widget(a, "text_input", "OPUS spectra directory", key="qc_dir")
        if directory.strip():
            state.rc7_qc_source_mode = "independent"
        st.caption("Independent QC keeps its own OPUS folder and review.")
    stale = guard_source(state, directory)
    if stale:
        st.warning(f"{stale} Run QC again before reviewing, exporting or freezing.")
    if directory.strip() and not st.session_state.get("rc6_value_qc_output"):
        reset_remembered("qc_output", str(Path(directory).expanduser().parent / "Spectral_QC"))
    output = remember_widget(st, "text_input", "QC output directory", key="qc_output")
    batch_label = remember_widget(st, "text_input", "Lab / instrument / batch label (optional)",
                                  key="qc_batch_label")
    mapping = None
    with st.expander("Advanced: optional identity mapping"):
        epoch = st.session_state.get("qc_mapping_epoch", 0)
        upload = st.file_uploader("CSV / Excel mapping", type=["csv", "xlsx"],
                                  key=f"qc_mapping_upload_{epoch}")
        if upload is not None:
            st.session_state.rc6_qc_mapping = (upload.name, upload.getvalue())
        saved_mapping = st.session_state.get("rc6_qc_mapping")
        if saved_mapping is not None:
            st.caption(f"Selected mapping: {saved_mapping[0]}")
            if st.button("Remove identity mapping"):
                st.session_state.pop("rc6_qc_mapping", None)
                st.session_state.qc_mapping_epoch = st.session_state.get("qc_mapping_epoch", 0) + 1
                st.rerun()
            try:
                excel = saved_mapping[0].lower().endswith(".xlsx")
                sheet = 0
                if excel:
                    with pd.ExcelFile(io.BytesIO(saved_mapping[1])) as book:
                        sheet = remember_widget(st, "selectbox", "Mapping worksheet",
                                                key="qc_mapping_sheet", options=book.sheet_names)
                mapping = read_mapping(io.BytesIO(saved_mapping[1]), excel=excel, sheet_name=sheet)
            except Exception as exc:
                st.error(f"Invalid mapping: {exc}")
                st.stop()
    a, b = st.columns(2)
    pattern = remember_widget(a, "selectbox", "Filename pattern", key="qc_pattern",
                              options=["Auto", "NSSH", "Sample_Replicate", "Custom"])
    expected = remember_widget(b, "number_input", "Expected replicates per sample",
                               key="qc_expected", min_value=2, max_value=20, value=3)
    if pattern == "Custom":
        pattern = remember_widget(
            st, "text_input", "Custom regular expression with sample and replicate named groups",
            key="qc_custom_pattern",
            value=r"(?P<sample>.+)_(?P<replicate>[0-9]+)\.[0-9]+",
        )
    range_mode = remember_widget(
        st, "radio", "QC spectral range", key="qc_range_mode", options=["auto", "manual"],
        format_func=lambda mode: (
            "Automatic — read full native OPUS range"
            if mode == "auto" else "Manual — require complete measured coverage"
        ),
    )
    if range_mode == "manual":
        a, b = st.columns(2)
        lower = remember_widget(a, "number_input", "QC minimum (cm⁻¹)",
                                key="qc_lower", value=600., format="%.4f")
        upper = remember_widget(b, "number_input", "QC maximum (cm⁻¹)",
                                key="qc_upper", value=4000., format="%.4f")
    else:
        lower, upper = None, None
        st.caption(
            "Reads native absorbance-block FXV/LXV and valid point count (NPT) from OPUS files. "
            "Uses the common measured interval across readable, matched scans, without nominal "
            "bounds or extrapolation. A narrow scan can limit the batch range; use manual bounds "
            "to flag insufficient coverage instead."
        )
    exclude_co2 = remember_widget(st, "checkbox",
                                  "Exclude CO₂ from global metrics (retain regional diagnostic)",
                                  key="qc_exclude_co2")
    with st.expander("Advanced regional diagnostics"):
        st.caption(
            "Regional RMSE identifies where spectra disagree. In USDA-inspired mode it is "
            "diagnostic only. The default windows are approximate and do not restrict global QC."
        )
        region_input = remember_widget(
            st, "text_input", "Diagnostic regions (lower-upper, comma separated)",
            key="qc_region_input",
            value=", ".join(f"{a}-{b}" for a, b in REGIONS),
        )
    try:
        regions = tuple(tuple(map(float, token.strip().split("-")))
                        for token in region_input.split(",") if token.strip())
        if any(len(region) != 2 or region[0] >= region[1] for region in regions):
            raise ValueError("Use increasing lower-upper bounds.")
    except ValueError as exc:
        st.error(f"Invalid diagnostic regions: {exc}")
        st.stop()

    if st.button("Reset acceptance defaults"):
        for key, value in {
            "qc_mode": "USDA-inspired", "qc_similarity": 99.6,
            "qc_nrmse_pass": 2., "qc_nrmse_fail": 5.,
            "qc_strategy": "Routine QC", "qc_method": "USDA-style",
        }.items():
            reset_remembered(key, value)
        for key in list(st.session_state):
            if key.startswith(("rc6_value_qc_reg_", "_rc6_value_qc_reg_")):
                del st.session_state[key]
    strategy = remember_widget(st, "selectbox", "Decision strategy", key="qc_strategy",
                               options=DECISION_STRATEGIES)
    if strategy == "Routine QC":
        comparison_method = remember_widget(
            st, "radio", "Active comparison method", options=COMPARISON_METHODS,
            key="qc_method", horizontal=True
        )
    else:
        comparison_method = "All-pairwise"
        st.caption("Spectral screening uses all-pairwise comparisons.")
    st.caption("Dual Pearson evaluation is always enabled.")
    mode = remember_widget(st, "radio", "QC mode", options=["USDA-inspired", "Advanced"],
                           key="qc_mode", horizontal=True)
    similarity = remember_widget(
        st, "number_input", "Minimum spectral similarity (Pearson r, %; strict >)",
        min_value=0., max_value=99.9999, value=99.6, step=.1, format="%.4f", key="qc_similarity",
    )
    st.caption(
        "99.6% is a USDA-inspired default; this Pearson implementation "
        "is not claimed to be numerically identical to OPUS Quick Compare."
    )
    nrmse_pass, nrmse_fail = 2., 5.
    regional_limits = {}
    if mode == "Advanced":
        a, b = st.columns(2)
        nrmse_pass = remember_widget(a, "number_input", "NRMSE pass limit (%)",
                                     value=2., key="qc_nrmse_pass")
        nrmse_fail = remember_widget(b, "number_input", "NRMSE fail limit (%)",
                                     value=5., key="qc_nrmse_fail")
        st.warning("NRMSE limits are exploratory, not validated acceptance standards.")
        with st.expander("Optional validated regional RMSE thresholds"):
            for low, high in regions:
                region_key = f"{low}_{high}"
                if remember_widget(st, "checkbox", f"Enforce {low:g}–{high:g} cm⁻¹",
                                   key=f"qc_reg_on_{region_key}"):
                    a, b = st.columns(2)
                    p = remember_widget(a, "number_input", "Pass limit (AU)", value=.01,
                                        key=f"qc_reg_p_{region_key}")
                    f = remember_widget(b, "number_input", "Fail limit (AU)", value=.03,
                                        key=f"qc_reg_f_{region_key}")
                    regional_limits[(low, high)] = (p, f)
    try:
        criteria = Criteria(
            similarity, mode == "Advanced", nrmse_pass, nrmse_fail, regional_limits,
            strategy, comparison_method,
        )
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    if not directory.strip():
        st.info("Choose an OPUS folder to preview sample grouping.")
        st.stop()
    try:
        directory = str(Path(directory).expanduser().resolve())
        inventory = file_inventory(directory)
        names = [path.name for path in list_opus_files(directory)]
        groups, unmatched, detected = resolve_groups(names, pattern, mapping)
        preview = []
        for sample, scans in groups.items():
            issues = group_issues(scans, expected)
            preview.append({
                "Sample ID": sample, "Replicates": len(scans),
                "Expected": expected, "Grouping": "Review" if any(issues.values()) else "Complete",
                **{key: str(value) for key, value in issues.items()},
                "Files": "; ".join(scan.filename for scan in scans),
            })
    except (OSError, ValueError) as exc:
        invalidate_source(st.session_state, "The spectral source is unavailable.")
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.error(f"Unable to preview naming pattern: {exc}")
        st.stop()
    st.subheader("Grouping preview")
    st.write(f"Detected rule: {detected} | {len(names)} files | {len(groups)} identified samples")
    st.dataframe(pd.DataFrame(preview), hide_index=True)
    if unmatched:
        st.warning(f"{len(unmatched)} unmatched files; these will not be treated as passing.")
        with st.expander("Unmatched files"):
            st.dataframe(pd.DataFrame({"File Name": unmatched}), hide_index=True)
    previous_config = st.session_state.get("qc_config")
    if previous_config and previous_config[1] != inventory:
        invalidate_source(st.session_state, "Input files have changed.")
    config = (directory, inventory, pattern, batch_label, expected, lower, upper,
              exclude_co2, regions, mapping, range_mode)
    st.session_state.rc6_qc_setup = (config, criteria, output)
    if st.button("Run QC", type="primary", disabled=not names):
        progress = st.progress(0., text="Reading spectra")
        try:
            data = prepare_batch(
                directory, pattern=pattern, batch_label=batch_label, expected=expected,
                lower=lower, upper=upper, exclude_co2=exclude_co2, regions=regions,
                cache_root=Path.home() / ".soil_mir_app" / "qc_cache",
                progress=lambda fraction, message: progress.progress(fraction, text=message),
                mapping=mapping, range_mode=range_mode,
            )
            if data.inventory != inventory or file_inventory(directory) != inventory:
                raise ValueError("Input files changed during QC. Run QC again.")
            completed_batch(st.session_state)
            st.session_state.qc_data = data
            st.session_state.qc_config = config
            st.session_state.qc_reviews = {}
            st.session_state.qc_review_history = []
            st.session_state.qc_review_revision = st.session_state.get("qc_review_revision", 0) + 1
            st.session_state.pop("qc_frozen", None)
            st.session_state.qc_review_criteria = criteria
            progress.progress(1., text="QC complete")
            request_section("qc", "Overview")
            st.rerun()
        except Exception as exc:
            invalidate_source(st.session_state, "QC did not complete successfully.")
            st.session_state.pop("qc_data", None)
            st.error(f"QC failed: {exc}")

else:
    state = st.session_state
    current_directory = effective_directory(state)
    stale = guard_source(state, current_directory)
    if source_mode(state) == "linked" and (
            not current_directory or not Path(current_directory).is_dir()):
        invalidate_source(state, "The linked Modeling Data directory is unavailable.")
        stale = "The linked Modeling Data directory is unavailable."
    if stale:
        st.warning(f"{stale} Previous QC results are not current. Run QC again in Setup.")
        previous = state.get("qc_config")
        if previous:
            st.caption(f"Previous source: {previous[0]}")
        st.caption(f"Current source: {current_directory or 'Not selected'}")
        if st.button("Go to Setup"):
            request_section("qc", "Setup")
            st.rerun()
        st.stop()
    context = st.session_state.get("rc6_qc_setup")
    if context is None:
        st.info("Complete Setup and run QC first.")
        st.stop()
    config, criteria, output = context
    directory, inventory, _, batch_label, expected, *_ = config
    try:
        if canonical_directory(directory) != canonical_directory(current_directory):
            invalidate_source(state, "The spectral source changed.")
            st.warning("The spectral source changed. Return to Setup and run QC again.")
            st.stop()
        if file_inventory(directory) != inventory:
            invalidate_source(state, "Input files have changed.")
            st.warning("Input files have changed. Return to Setup and run QC again.")
            st.stop()
    except (OSError, ValueError) as exc:
        invalidate_source(state, "The spectral source is unavailable.")
        st.error(str(exc))
        st.stop()
strategy = criteria.decision_strategy
comparison_method = criteria.comparison_method
if "qc_data" not in st.session_state:
    if section != "Setup":
        st.info("Run QC in Setup to populate this section.")
    st.stop()
if st.session_state.get("rc7_qc_stale_reason") or st.session_state.get("qc_config") != config:
    st.session_state.pop("qc_frozen", None)
    st.warning("Inputs or files have changed. Run QC again to refresh metrics.")
    st.stop()
data = st.session_state.qc_data
if st.session_state.get("qc_review_criteria") != criteria:
    # Archive review decisions rather than silently applying them under a new rule.
    archive = st.session_state.setdefault("qc_review_archive", [])
    if st.session_state.qc_reviews:
        archive.append((st.session_state.qc_review_criteria, st.session_state.qc_reviews.copy()))
    st.session_state.qc_reviews = {}
    st.session_state.qc_review_history = []
    st.session_state.qc_review_revision = st.session_state.get("qc_review_revision", 0) + 1
    st.session_state.pop("qc_frozen", None)
    st.session_state.qc_review_criteria = criteria
    st.session_state.qc_review_notice = (
        "QC rule changed: cached metrics reused; review decisions require reconfirmation."
    )
    st.info(st.session_state.qc_review_notice)

if section == "Setup":
    st.success("QC results are current. Open Overview or another section.")
    st.stop()
if not output.strip() and section in ("Export", "Calibration"):
    st.warning("Choose a QC output directory in Setup.")
    st.stop()
st.caption(
    f"{batch_label or Path(directory).name} | {strategy} / {comparison_method} | "
    f"{criteria.similarity:g}% | {expected} replicates"
)
if st.session_state.get("qc_review_notice"):
    st.success(st.session_state.pop("qc_review_notice"))
cache_key = st.session_state.get("qc_review_revision", 0)
if st.session_state.get("rc6_qc_table_revision") != cache_key or (
    "rc6_qc_tables" not in st.session_state
):
    st.session_state.rc6_qc_tables = evaluate_batch(data, criteria, st.session_state.qc_reviews)
    st.session_state.rc6_qc_table_revision = cache_key
tables = st.session_state.rc6_qc_tables
summary = tables["Sample QC"]
comparison = tables["Method Comparison"]
timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")

if section == "Overview":
    overview = tables["Overview"].set_index("Metric")["Value"]
    st.subheader(f"QC summary — {strategy} / {comparison_method}")
    keys = ["Consistent", "Inconsistent", "Incomplete"] if strategy == "Routine QC" else [
        "Pass", "Review", "Fail", "Incomplete",
    ]
    for col, key in zip(st.columns(len(keys)), keys):
        col.metric(key, int(overview[key]))
    st.caption(
        f"Identified samples: {int(overview['Identified samples'])}; "
        f"evaluable samples: {int(overview['Evaluable samples'])}; "
        f"unmatched files: {int(overview['Unmatched files'])}; "
        f"read errors: {int(overview['Read errors'])}; "
        f"input validation errors: {int(overview['Input validation errors'])}."
    )
    if data.effective_lower is not None:
        st.write(
            f"**Shared comparison bounds:** {data.effective_lower:.4f}–"
            f"{data.effective_upper:.4f} cm⁻¹ (no extrapolation)."
        )
        if data.range_mode == "auto" and data.native_range_count > 1:
            st.warning(
                f"{data.native_range_count} distinct native ranges found; the full envelope is "
                f"{data.native_envelope_lower:.4f}–{data.native_envelope_upper:.4f} cm⁻¹. "
                "Only the common measured interval is compared. Review native bounds in File QC. "
                "Switch to Manual to require a fixed interval."
            )
    if int(overview["Evaluable samples"]) == 0:
        st.metric("Sample pass rate", "N/A")
        st.warning(
            "No complete samples could be evaluated. Inspect input errors and native ranges."
        )
    else:
        a, b = st.columns(2)
        a.metric("Pass rate (all identified)", f"{overview['Sample pass rate (%)']:.2f}%")
        b.metric("Pass rate (evaluable only)", f"{overview['Evaluable sample pass rate (%)']:.2f}%")
    if not summary.empty:
        statuses = remember_widget(
            st, "multiselect", "Show sample statuses", key="qc_status_filter",
            options=["Pass", "Review", "Fail", "Incomplete"],
            default=["Pass", "Review", "Fail", "Incomplete"],
        )
        filtered = summary[summary["Sample QC"].isin(statuses)]
        st.dataframe(filtered, hide_index=True)

    pending_count = (tables["File QC"]["Manual decision"] == "Pending review").sum()
    st.write(f"Pending review: {pending_count} files")
    for col, target in zip(st.columns(3), ("Review", "Diagnostics", "Export")):
        if col.button(f"Open {target}"):
            request_section("qc", target)
            st.rerun()

elif section == "Diagnostics":
    st.subheader("Dual evaluation — comparison of strategies")
    st.caption(
        "Both use the same raw Pearson coefficients and strict threshold. USDA-style uses "
        "replicate ID 1 as reference (self = 100%); all-pairwise tests every pair. "
        "Not validated against OPUS Quick Compare. Advanced NRMSE/region gates affect only "
        "active required pairs and review decisions, not this Pearson-only comparison."
    )
    comparison = tables["Method Comparison"]
    sensitivity = tables["Threshold Sensitivity"]
    current = sensitivity.loc[sensitivity["Threshold (%)"] == criteria.similarity].iloc[0]
    n = int(current["Comparable samples"])
    a, b, c = st.columns(3)
    a.metric("USDA-style pass rate", f"{current['USDA-style pass rate (%)']:.2f}%" if n else "N/A")
    b.metric("All-pairwise Pearson pass rate",
             f"{current['All-pairwise pass rate (%)']:.2f}%" if n else "N/A")
    c.metric("Method agreement", f"{current['Agreement (%)']:.2f}%" if n else "N/A")
    st.caption(
        f"Comparable samples: {n}; not comparable: {int(current['Not comparable'])}; "
        f"USDA-style pass / all-pair not pass: {int(current['USDA pass / all-pair not pass'])}."
    )
    @st.fragment
    def method_comparison():
        st.subheader("Method comparison and threshold sensitivity")
        view = remember_widget(st, "radio", "Comparison view",
                               options=["Both", "Disagreements", "Not comparable"],
                               horizontal=True, key="qc_comparison_view")
        displayed = comparison
        if view == "Disagreements":
            displayed = comparison.loc[comparison["Method agreement"] == "Disagree"]
        elif view == "Not comparable":
            displayed = comparison.loc[comparison["Method agreement"] == "Not comparable"]
        st.dataframe(displayed, hide_index=True)
        st.download_button(
            "Export Method Comparison", comparison.to_csv(index=False).encode("utf-8-sig"),
            file_name="Method_Comparison.csv", mime="text/csv",
        )
        st.dataframe(sensitivity, hide_index=True)
        st.download_button(
            "Export Threshold Sensitivity", sensitivity.to_csv(index=False).encode("utf-8-sig"),
            file_name="Threshold_Sensitivity.csv", mime="text/csv",
        )
    method_comparison()

    if not summary.empty:
        a, b = st.columns(2)
        for col, metric in [(a, "Min similarity (%)"), (b, "Max NRMSE (%)")]:
            values = summary[metric].dropna()
            if not values.empty:
                fig, ax = plt.subplots()
                ax.hist(values, bins=min(20, len(values)))
                ax.set_xlabel(metric)
                ax.set_ylabel("Samples")
                col.pyplot(fig)
                plt.close(fig)
        st.subheader("Sample inspector")
        sample = remember_widget(st, "selectbox", "Sample ID", key="qc_sample",
                                 options=summary["Sample ID"].tolist())
        sample_row = summary.loc[summary["Sample ID"] == sample].iloc[0]
        st.write("**Suspected file:**", sample_row["Suspected File"] or "None uniquely identified")
        st.write("**Recommended action:**", sample_row["Recommended Action"])
        st.write("**USDA-style:**", sample_row["USDA-style status"],
                 "| **All-pairwise Pearson:**", sample_row["All-pairwise Pearson status"])
        st.dataframe(comparison.loc[comparison["Sample ID"] == sample], hide_index=True)
        pair_frame = tables["Pairwise QC"]
        if not pair_frame.empty:
            shown_pairs = pair_frame.loc[pair_frame["Sample ID"] == sample].copy()
            shown_pairs["Reference comparison"] = shown_pairs["Reference comparison"].map(
                {True: "Yes", False: "No — all-pairwise only"}
            )
            shown_pairs = shown_pairs.rename(columns={
                "Reference comparison": "Used in USDA-style comparison",
            })
            st.caption(
                "Read-only method membership: Yes = pair includes replicate 1; "
                "No = only used in all-pairwise comparison. Not a QC pass indicator."
            )
            st.dataframe(shown_pairs, hide_index=True)
        regional_frame = tables["Regional QC"]
        if not regional_frame.empty:
            with st.expander("Regional QC"):
                st.dataframe(regional_frame.loc[regional_frame["Sample ID"] == sample],
                             hide_index=True)
        filenames = [scan.filename for scan in data.groups[sample]]
        visible = remember_widget(st, "multiselect", "Show spectra", options=filenames,
                                  default=filenames, key=f"qc_plot_{sample}")
        st.subheader("Spectral visualization")
        st.caption(
            "Preview only. QC classification always uses raw absorbance. MSC uses the mean "
            "of all aligned replicates in the selected sample, not only visible curves. "
            "SG derivatives follow the modeling convention (per spectral point)."
        )
        method = remember_widget(
            st, "selectbox", "Display preprocessing", key="qc_preview_method",
            options=["Raw Spectra"] + [m for m in PREPROCESSING_NAMES if m != "Raw Spectra"],
            disabled=sample not in data.aligned,
        )
        window, poly = 11, 2
        if method not in NO_SG_METHODS:
            a, b = st.columns(2)
            window = remember_widget(a, "number_input", "SG window (points)",
                                     key="qc_preview_window", min_value=3, value=11, step=2)
            poly = remember_widget(b, "number_input", "SG polynomial order",
                                   key="qc_preview_poly", min_value=1, value=2)
        plot_axis, processed = None, {}
        if sample in data.aligned:
            try:
                plot_axis, processed = preview_spectra(data, sample, method, window, poly)
            except ValueError as exc:
                st.warning(f"Cannot preview {method}: {exc}")
        if "SNV" in method:
            unit = "Normalized signal"
        elif "Deriv" in method:
            unit = ("Derivative (per point)" if "2nd" not in method
                    else "Second derivative (per point²)")
        else:
            unit = "Absorbance (AU)"
        fig, ax = plt.subplots()
        for i, name in enumerate(filenames):
            if name not in visible:
                continue
            if name in processed:
                values, axis = processed[name], plot_axis
            elif method == "Raw Spectra" and name in data.raw:
                values, axis = data.raw[name]
            else:
                continue
            ax.plot(axis, values, label=name, color=f"C{i%10}",
                    linewidth=2 if name == sample_row["Suspected File"] else 1)
        ax.set_title(f"Spectral overlay — {method}")
        ax.set_xlabel("Wavenumber (cm⁻¹)")
        ax.set_ylabel(unit)
        ax.invert_xaxis()
        if ax.lines:
            ax.legend(fontsize="small")
        st.pyplot(fig)
        plt.close(fig)
        if processed:
            fig, ax = plt.subplots()
            for i, name in enumerate(filenames):
                for other in filenames[i+1:]:
                    if (name in visible and other in visible
                            and name in processed and other in processed):
                        ax.plot(
                            plot_axis, processed[name] - processed[other], label=f"{name} - {other}"
                        )
            ax.axhline(0, color="gray", linewidth=.8)
            ax.invert_xaxis()
            ax.set_title(f"Pairwise difference — {method}")
            ax.set_xlabel("Wavenumber (cm⁻¹)")
            ax.set_ylabel(f"Difference: {unit}")
            if len(ax.lines) > 1:
                ax.legend(fontsize="small")
            st.pyplot(fig)
            plt.close(fig)

        if st.button("Review selected sample"):
            request_section("qc", "Review")
            st.rerun()
    with st.expander("Exploratory MAD thresholds"):
        st.dataframe(tables["Threshold diagnostics"], hide_index=True)

elif section == "Review":
    file_table = tables["File QC"]
    cols = st.columns(4)
    for col, choice in zip(cols, DECISION_ORDER):
        col.metric(choice, int((file_table["Manual decision"] == choice).sum()))
    st.dataframe(file_table["Recommended decision"].value_counts().rename("Recommended files"))
    if strategy == "Routine QC":
        st.dataframe(summary, hide_index=True)
    st.subheader("Batch review decisions")
    st.caption(
        "Apply the active policy to unreviewed files only. Routine QC recommends Keep all "
        "or Rescan all for valid samples. Existing manual decisions remain untouched; "
        "input issues and ambiguous screening cases stay pending. No source files are changed."
    )
    pending_files = tables["File QC"].loc[
        tables["File QC"]["Manual decision"] == "Pending review"
    ].copy()
    st.write(f"Pending review: {len(pending_files)} files")
    if not pending_files.empty:
        pending_files["Pending cause"] = pending_files.apply(
            lambda row: "Explicitly saved Pending" if row["Decision source"] != "Not reviewed"
            else "Awaiting batch application" if row["Recommended decision"] != "Pending review"
            else row["Recommendation reason"], axis=1,
        )
        st.dataframe(pending_files["Pending cause"].value_counts().rename("Files"),
                     hide_index=False)
    if strategy == "Routine QC":
        conflicts = tables["File QC"].loc[
            (tables["File QC"]["Manual decision"] != "Pending review")
            & (tables["File QC"]["Manual decision"] != tables["File QC"]["Recommended decision"])
        ]
        if not conflicts.empty:
            st.warning(
                f"{len(conflicts)} saved decisions differ from Routine QC recommendations. "
                "Resolve overrides before freezing a whole-sample calibration selection."
            )
    if st.button("Apply recommended decisions to unreviewed files"):
        updated = recommended_reviews(tables, st.session_state.qc_reviews)
        count = len(updated) - len(st.session_state.qc_reviews)
        if set_review_state(updated, f"Applied {count} recommended decisions."):
            st.rerun()
        st.info("No additional unreviewed files have an actionable recommendation.")
    st.caption(
        "Decision source: Not reviewed = no saved decision. Manual = explicitly saved "
        "by you. Applied recommendation = saved by the batch action."
    )
    history = st.session_state.get("qc_review_history", [])
    revision = st.session_state.get("qc_review_revision", 0)
    with st.expander("Reset or undo review decisions"):
        st.caption(
            "Clear removes all saved decisions and reasons, not QC metrics or spectra. "
            "Undo restores the preceding saved state (up to 20 actions in this session). "
            "History resets after Run QC or a criteria change. Exported files and saved "
            "manifests are not modified; a changed selection must be frozen again."
        )
        confirmed_clear = st.checkbox(
            "Confirm clearing all manual and applied decisions",
            key=f"qc_confirm_clear_{revision}",
            disabled=not st.session_state.qc_reviews,
        )
        clear_col, undo_col = st.columns(2)
        if clear_col.button(
            "Clear all decisions", disabled=not confirmed_clear or not st.session_state.qc_reviews
        ):
            count = len(st.session_state.qc_reviews)
            if set_review_state({}, f"Cleared {count} decisions. Use Undo to restore them."):
                st.rerun()
        if undo_col.button("Undo last decision change", disabled=not history):
            updated, remaining = review_history_undo(st.session_state.qc_reviews, history)
            if set_review_state(updated, "Restored previous review state.", history=remaining):
                st.rerun()
    with st.expander("All files and unresolved inputs", expanded=True):
        file_table = tables["File QC"]
        selected = remember_widget(
            st, "multiselect", "Filter file diagnosis", key="qc_file_filter",
            options=["Consistent", "Suspected", "Needs review", "Invalid", "Unmatched"],
            default=["Consistent", "Suspected", "Needs review", "Invalid", "Unmatched"],
        )
        show_pending = remember_widget(st, "checkbox", "Pending decisions only", key="qc_pending")
        decisions_filter = remember_widget(
            st, "multiselect", "Filter saved decisions", key="qc_decision_filter",
            options=list(DECISION_ORDER), default=list(DECISION_ORDER),
        )
        sample_options = sorted(file_table["Sample ID"].dropna().astype(str).unique().tolist())
        chosen_samples = remember_widget(
            st, "multiselect", "Filter sample IDs (empty = all)", key="qc_sample_filter",
            options=sample_options,
        )
        display = file_table.loc[file_table["File Diagnosis"].isin(selected)
                                 & file_table["Manual decision"].isin(decisions_filter)]
        if chosen_samples:
            display = display.loc[display["Sample ID"].isin(chosen_samples)]
        if show_pending:
            display = display.loc[display["Manual decision"] == "Pending review"]
        detailed = remember_widget(st, "checkbox", "Show detailed metrics and error messages",
                                   key="qc_detailed")
        columns = [
            "Sample ID", "Replicate ID", "File Name", "File Diagnosis", "Recommended decision",
            "Manual decision", "Decision source", "Recommendation reason",
        ]
        review_editor(display if detailed else display.reindex(columns=columns),
                      "all_files", file_table)

    if not summary.empty:
        st.subheader("Review individual sample")
        sample = remember_widget(st, "selectbox", "Sample ID", key="qc_sample",
                                 options=summary["Sample ID"].tolist())
        filenames = [scan.filename for scan in data.groups[sample]]
        file_rows = tables["Replicate Diagnosis"]
        concise = ["Replicate ID", "File Name", "File Diagnosis", "Recommended decision",
                   "Manual decision", "Decision source", "Min similarity (%)",
                   "Recommendation reason"]
        review_editor(file_rows.loc[file_rows["Sample ID"] == sample, concise],
                      "sample", tables["File QC"])
        st.subheader("Review decision")
        name = remember_widget(st, "selectbox", "Exact OPUS file", options=filenames,
                               key=f"qc_file_{sample}")
        previous = st.session_state.qc_reviews.get(name, {})
        choices = list(DECISION_ORDER)
        revision = st.session_state.get("qc_review_revision", 0)
        with st.form(f"qc_review_{name}_{criteria}_{revision}"):
            decision = st.radio("Decision", choices,
                                index=choices.index(previous.get("decision", choices[0])))
            reason = st.text_area("Reason (optional)", value=previous.get("reason", ""))
            if st.form_submit_button("Save review decision"):
                save_review_edits([{
                    "File Name": name, "Manual decision": decision, "Manual reason": reason,
                }], tables["File QC"])
    if data.unmatched:
        with st.expander("Resolve unmatched files for optional calibration"):
            unmatched_name = st.selectbox("Unmatched filename", data.unmatched)
            unmatched_reason = st.text_input("Reason for excluding unmatched file (optional)")
            if st.button("Confirm exclusion of unmatched file"):
                save_review_edits([{
                    "File Name": unmatched_name, "Manual decision": "Exclude",
                    "Manual reason": unmatched_reason,
                }], tables["File QC"])

elif section == "Export":
    st.subheader("Export QC results")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    export_view = remember_widget(st, "radio", "Export view", key="qc_export_view",
                                  options=["Agreed spectra", "Review decisions", "Rescan list"],
                                  horizontal=True)
    if export_view == "Agreed spectra":
        agreed = tables["Agreed Spectra"]
        st.caption(
            "Keep recommendations under the active policy, not an approved PLSR selection. "
            "Manual decisions remain separate."
        )
        st.write(f"{len(agreed)} agreed spectra across {agreed['Sample ID'].nunique()} samples.")
        review_editor(agreed, "agreed", tables["File QC"])
        st.download_button("Export Agreed Spectra", agreed.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"Agreed_Spectra_{timestamp}.csv", mime="text/csv")
    elif export_view == "Review decisions":
        review = tables["Review decisions"]
        st.caption("Recorded manual or applied-recommendation decisions. Pending is not approval.")
        review_editor(review, "export_review", tables["File QC"])
        kept = review.loc[review["Manual decision"] == "Keep"]
        st.download_button("Export Reviewed Keep List",
                           kept.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"Reviewed_Keep_{timestamp}.csv", mime="text/csv")
    else:
        sample_rescans = tables["Sample Rescan List"]
        st.markdown("**Sample-level rescan list**")
        st.dataframe(sample_rescans, hide_index=True)
        st.download_button(
            "Export Sample Rescan List", sample_rescans.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"Sample_Rescan_List_{timestamp}.csv", mime="text/csv",
        )
        st.markdown("**Replicate-level rescan list**")
        rescan = tables["Rescan List"]
        rescan_mode = remember_widget(st, "radio", "Rescan export",
                                     options=["All", "Confirmed only", "Suggestions only"],
                                     horizontal=True, key="qc_rescan_mode")
        if rescan_mode == "Confirmed only":
            rescan = rescan.loc[rescan["Type"] == "Confirmed rescan"]
        elif rescan_mode == "Suggestions only":
            rescan = rescan.loc[rescan["Type"] != "Confirmed rescan"]
        st.dataframe(rescan, hide_index=True)
        st.caption(
            "Edit exact filenames below. Whole-sample or missing-replicate suggestions "
            "are not individual files and cannot be edited directly."
        )
        file_table = tables["File QC"]
        affected_samples = set(rescan["Sample ID"].dropna()) - {""}
        affected_files = set(rescan["File Name"].dropna()) - {""}
        related = file_table.loc[
            file_table["Sample ID"].isin(affected_samples)
            | file_table["File Name"].isin(affected_files)
        ]
        review_editor(related.reindex(columns=[
            "Sample ID", "File Name", "File Diagnosis", "Recommended decision",
            "Manual decision", "Manual reason",
        ]), "rescan", file_table)
        st.download_button("Export Rescan List", rescan.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"Rescan_List_{timestamp}.csv", mime="text/csv")
    if st.button("Save Excel QC report"):
        try:
            folder = Path(output).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"Spectral_QC_Report_{timestamp}.xlsx"
            with path.open("xb") as stream:
                stream.write(report_bytes(tables))
            st.success(f"Saved {path}")
            st.session_state.qc_saved_folder = str(folder)
        except (OSError, ValueError) as exc:
            st.error(str(exc))
    if st.session_state.get("qc_saved_folder") and st.button("Open QC results folder"):
        try:
            open_local_folder(st.session_state.qc_saved_folder)
        except (OSError, RuntimeError) as exc:
            st.warning(str(exc))
    st.subheader("Save or restore review")
    st.caption("Review snapshots are local JSON files; no spectra are uploaded.")
    restore = st.file_uploader("Restore QC manifest for the current input and criteria",
                               type=["json"])
    if restore and st.button("Restore saved review"):
        try:
            payload = json.loads(restore.getvalue())
            validate_manifest(payload, directory)
            current = input_settings(data)
            if payload["input"] != current or criteria_from_dict(payload["criteria"]) != criteria:
                raise ValueError("Input settings or thresholds differ from saved review.")
            if set_review_state(payload["decisions"], "Restored saved review."):
                st.rerun()
            st.info("Saved review already matches the current decisions.")
        except Exception as exc:
            st.error(f"Cannot restore: {exc}")

    if st.button("Save review snapshot"):
        try:
            folder = Path(output).expanduser() / f"QC_{timestamp}"
            folder.mkdir(parents=True, exist_ok=False)
            payload = build_manifest(data, criteria, tables, st.session_state.qc_reviews)
            save_manifest(folder / "QC_Manifest.json", payload)
            (folder / "Spectral_QC_Report.xlsx").write_bytes(report_bytes(tables))
            st.session_state.qc_saved_folder = str(folder)
            st.success(f"Review saved in {folder}")
        except Exception as exc:
            st.error(str(exc))
    st.markdown("**Export spectra by review decision**")
    st.caption(
        "Copy original OPUS files only, with exact filenames and verified checksums. "
        "This uses saved decisions, not unconfirmed recommendations. Apply recommended "
        "decisions first if you want to export those files as Keep. Pending files are "
        "not approved for calibration. This export does not freeze a calibration manifest."
    )
    export_choices = remember_widget(
        st, "multiselect", "Decisions to export", key="qc_export_choices",
        options=["Keep", "Exclude", "Rescan required", "Pending review"],
        default=["Keep"],
    )
    try:
        export_rows = decision_export_rows(
            tables["File QC"], st.session_state.qc_reviews, export_choices
        ) if export_choices else []
        st.write(f"{len(export_rows)} spectra selected for copying.")
        if st.button("Export selected OPUS spectra", disabled=not export_rows):
            try:
                target, count = export_decision_spectra(
                    data, tables, st.session_state.qc_reviews, export_choices,
                    Path(output).expanduser() / f"QC_Spectra_{timestamp}", criteria,
                )
                st.session_state.qc_export_folder = str(target)
                st.success(f"Copied and verified {count} OPUS files to {target}")
            except (OSError, ValueError) as exc:
                st.error(f"Export failed: {exc}")
    except ValueError as exc:
        st.error(str(exc))
    if st.session_state.get("qc_export_folder"):
        st.code(st.session_state.qc_export_folder)
        if st.button("Open exported spectra folder"):
            try:
                open_local_folder(st.session_state.qc_export_folder)
            except (OSError, RuntimeError) as exc:
                st.warning(str(exc))

elif section == "Calibration":
    st.subheader("Optional: use reviewed spectra for calibration")
    st.warning(
        "QC does not change PLSR inputs unless you explicitly freeze and select a manifest "
        "on the Run page. All pending non-passing files must be resolved."
    )
    st.divider()
    min_retained = remember_widget(st, "number_input", "Minimum retained scans per sample",
                                   key="qc_min_retained", min_value=2, value=2)
    allow_single = remember_widget(
        st, "checkbox", "Allow explicitly reviewed single-scan exceptions", key="qc_allow_single"
    )
    frozen_options = (min_retained, allow_single)
    if (st.session_state.get("qc_frozen") and
            st.session_state.get("rc6_qc_frozen_options") != frozen_options):
        st.session_state.pop("qc_frozen", None)
        st.info("Calibration retention settings changed; freeze the selection again.")
    try:
        _, selection_preview = review_selection(
            data, tables, st.session_state.qc_reviews, min_retained=min_retained,
        )
        st.write(
            f"Retained: {len(selection_preview['retained'])}; "
            f"excluded: {len(selection_preview['excluded'])}; "
            f"pending: {len(selection_preview['pending'])}"
        )
        with st.expander("Retained scans by sample"):
            st.dataframe(pd.DataFrame(list(selection_preview["retained_counts"].items()),
                                      columns=["Sample ID", "Retained scans"]), hide_index=True)
    except ValueError as exc:
        st.warning(str(exc))
    confirmed = st.checkbox(
        "Confirm suggested Keep for passing groups and all recorded manual decisions",
        key=f"qc_freeze_confirm_{st.session_state.get('qc_review_revision', 0)}"
            f"_{min_retained}_{allow_single}",
    )
    if st.button("Freeze reviewed spectra for calibration", disabled=not confirmed):
        try:
            payload = build_manifest(
                data, criteria, tables, st.session_state.qc_reviews, freeze=True,
                min_retained=min_retained, allow_single=allow_single,
            )
            folder = Path(output).expanduser() / f"QC_Frozen_{timestamp}"
            folder.mkdir(parents=True, exist_ok=False)
            path = save_manifest(folder / "QC_Manifest.json", payload)
            (folder / "Spectral_QC_Report.xlsx").write_bytes(report_bytes(tables))
            selection = payload["selection"]
            pd.DataFrame([
                {"File Name": name, "Sample": payload["groups"][name]["sample"]}
                for name in selection["retained"]
            ]).to_csv(folder / "Reviewed_Spectra.csv", index=False, encoding="utf-8-sig")
            st.session_state.qc_frozen = str(path)
            st.session_state.rc6_qc_frozen_options = frozen_options
            st.session_state.qc_saved_folder = str(folder)
            st.success(f"Frozen manifest: {path}")
        except Exception as exc:
            st.error(str(exc))
    if st.session_state.get("qc_frozen"):
        st.code(st.session_state.qc_frozen)
        st.caption("Select this manifest explicitly on the Run page.")
