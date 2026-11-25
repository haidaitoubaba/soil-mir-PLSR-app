from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import hashlib
import io
import json

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from soil_mir.io.opus import list_opus_files
from soil_mir.qc import Criteria, REGIONS, group_issues
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


st.set_page_config(page_title="Spectral QC", page_icon="🔬", layout="wide")
st.title("Spectral QC")
st.caption("Standalone OPUS replicate consistency checks. No reference values required.")
st.info(
    "Use one measurement batch per folder. A consistency pass is not proof of chemical "
    "accuracy or correct sample identity. Original spectra are never changed."
)
if "qc_dir" not in st.session_state:
    st.session_state.qc_dir = ""
a, b = st.columns([5, 1])
if b.button("Browse", key="qc_browse"):
    try:
        chosen = choose_local_path("directory", prompt="Choose OPUS spectral QC folder")
        if chosen:
            st.session_state.qc_dir = str(chosen)
    except RuntimeError as exc:
        st.warning(str(exc))
directory = a.text_input("OPUS spectra directory", key="qc_dir")
batch_label = st.text_input("Lab / instrument / batch label (optional)")
mapping = None
with st.expander("Advanced: optional identity mapping"):
    upload = st.file_uploader("CSV / Excel mapping", type=["csv", "xlsx"])
    if upload is not None:
        try:
            excel = upload.name.endswith(".xlsx")
            sheet = 0
            if excel:
                with pd.ExcelFile(io.BytesIO(upload.getvalue())) as book:
                    sheet = st.selectbox("Mapping worksheet", book.sheet_names)
            mapping = read_mapping(io.BytesIO(upload.getvalue()), excel=excel, sheet_name=sheet)
        except Exception as exc:
            st.error(f"Invalid mapping: {exc}")
            st.stop()
a, b = st.columns(2)
pattern = a.selectbox("Filename pattern", ["Auto", "NSSH", "Sample_Replicate", "Custom"])
expected = b.number_input("Expected replicates per sample", min_value=2, max_value=20, value=3)
if pattern == "Custom":
    pattern = st.text_input(
        "Custom regular expression with sample and replicate named groups",
        value=r"(?P<sample>.+)_(?P<replicate>[0-9]+)\.[0-9]+",
    )
range_mode = st.radio(
    "QC spectral range",
    ["auto", "manual"],
    format_func=lambda mode: (
        "Automatic — read full native OPUS range"
        if mode == "auto" else "Manual — require complete measured coverage"
    ),
)
if range_mode == "manual":
    a, b = st.columns(2)
    lower = a.number_input("QC minimum (cm⁻¹)", value=600., format="%.4f")
    upper = b.number_input("QC maximum (cm⁻¹)", value=4000., format="%.4f")
else:
    lower, upper = None, None
    st.caption(
        "Reads native absorbance-block FXV/LXV and valid point count (NPT) from OPUS files. "
        "Uses the common measured interval across readable, matched scans, without nominal "
        "bounds or extrapolation. A narrow scan can limit the batch range; use manual bounds "
        "to flag insufficient coverage instead."
    )
exclude_co2 = st.checkbox("Exclude CO₂ from global metrics (retain regional diagnostic)")
with st.expander("Advanced regional diagnostics"):
    st.caption(
        "Regional RMSE identifies where spectra disagree. In USDA-inspired mode it is "
        "diagnostic only. The default windows are approximate and do not restrict global QC."
    )
    region_input = st.text_input(
        "Diagnostic regions (lower-upper, comma separated)",
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
    }.items():
        st.session_state[key] = value
    for key in list(st.session_state):
        if key.startswith("qc_reg_"):
            del st.session_state[key]
mode = st.radio("QC mode", ["USDA-inspired", "Advanced"], key="qc_mode", horizontal=True)
similarity = st.number_input(
    "Minimum spectral similarity (Pearson r, %; strict >)",
    min_value=0., max_value=99.9999, value=99.6, step=.1, format="%.4f", key="qc_similarity",
)
st.caption(
    "99.6% is a USDA-inspired default; this all-pair Pearson implementation "
    "is not claimed to be numerically identical to OPUS Quick Compare."
)
nrmse_pass, nrmse_fail = 2., 5.
regional_limits = {}
if mode == "Advanced":
    a, b = st.columns(2)
    nrmse_pass = a.number_input("NRMSE pass limit (%)", value=2., key="qc_nrmse_pass")
    nrmse_fail = b.number_input("NRMSE fail limit (%)", value=5., key="qc_nrmse_fail")
    st.warning("NRMSE limits are exploratory, not validated acceptance standards.")
    with st.expander("Optional validated regional RMSE thresholds"):
        for low, high in regions:
            region_key = f"{low}_{high}"
            if st.checkbox(f"Enforce {low:g}–{high:g} cm⁻¹", key=f"qc_reg_on_{region_key}"):
                a, b = st.columns(2)
                p = a.number_input("Pass limit (AU)", value=.01, key=f"qc_reg_p_{region_key}")
                f = b.number_input("Fail limit (AU)", value=.03, key=f"qc_reg_f_{region_key}")
                regional_limits[(low, high)] = (p, f)
try:
    criteria = Criteria(similarity, mode == "Advanced", nrmse_pass, nrmse_fail, regional_limits)
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
config = (directory, inventory, pattern, batch_label, expected, lower, upper,
          exclude_co2, regions, mapping, range_mode)
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
        st.session_state.qc_data = data
        st.session_state.qc_config = config
        st.session_state.qc_reviews = {}
        st.session_state.qc_review_history = []
        st.session_state.qc_review_revision = st.session_state.get("qc_review_revision", 0) + 1
        st.session_state.pop("qc_frozen", None)
        st.session_state.qc_review_criteria = criteria
        progress.progress(1., text="QC complete")
    except Exception as exc:
        st.session_state.pop("qc_data", None)
        st.error(f"QC failed: {exc}")
if "qc_data" not in st.session_state:
    st.stop()
if st.session_state.get("qc_config") != config:
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
    st.info("Threshold changed: cached metrics reused; review decisions require reconfirmation.")
tables = evaluate_batch(data, criteria, st.session_state.qc_reviews)
overview = tables["Overview"].set_index("Metric")["Value"]
st.subheader("QC summary — active all-pair QC")
for col, key in zip(st.columns(4), ["Pass", "Review", "Fail", "Incomplete"]):
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
    st.warning("No complete samples could be evaluated. Inspect input errors and native ranges.")
else:
    a, b = st.columns(2)
    a.metric("Pass rate (all identified)", f"{overview['Sample pass rate (%)']:.2f}%")
    b.metric("Pass rate (evaluable only)", f"{overview['Evaluable sample pass rate (%)']:.2f}%")
st.subheader("Dual evaluation — comparison of strategies")
st.caption(
    "Both use the same raw Pearson coefficients and strict threshold. USDA-style uses "
    "replicate ID 1 as reference (self = 100%); all-pairwise tests every pair. "
    "Not validated against OPUS Quick Compare. Advanced NRMSE/region gates affect only "
    "active all-pair QC and review decisions, not this Pearson-only comparison."
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
with st.expander("Method comparison and threshold sensitivity"):
    view = st.radio("Comparison view", ["Both", "Disagreements", "Not comparable"],
                    horizontal=True)
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
summary = tables["Sample QC"]
if not summary.empty:
    statuses = st.multiselect(
        "Show sample statuses", ["Pass", "Review", "Fail", "Incomplete"],
        default=["Pass", "Review", "Fail", "Incomplete"],
    )
    filtered = summary[summary["Sample QC"].isin(statuses)]
    st.dataframe(filtered, hide_index=True)
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
    sample = st.selectbox("Sample ID", summary["Sample ID"].tolist())
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
    visible = st.multiselect("Show spectra", filenames, default=filenames, key=f"qc_plot_{sample}")
    st.subheader("Spectral visualization")
    st.caption(
        "Preview only. QC classification always uses raw absorbance. MSC uses the mean "
        "of all aligned replicates in the selected sample, not only visible curves. "
        "SG derivatives follow the modeling convention (per spectral point)."
    )
    method = st.selectbox(
        "Display preprocessing",
        ["Raw Spectra"] + [m for m in PREPROCESSING_NAMES if m != "Raw Spectra"],
        disabled=sample not in data.aligned,
    )
    window, poly = 11, 2
    if method not in NO_SG_METHODS:
        a, b = st.columns(2)
        window = a.number_input("SG window (points)", min_value=3, value=11, step=2)
        poly = b.number_input("SG polynomial order", min_value=1, value=2)
    plot_axis, processed = None, {}
    if sample in data.aligned:
        try:
            plot_axis, processed = preview_spectra(data, sample, method, window, poly)
        except ValueError as exc:
            st.warning(f"Cannot preview {method}: {exc}")
    if "SNV" in method:
        unit = "Normalized signal"
    elif "Deriv" in method:
        unit = "Derivative (per point)" if "2nd" not in method else "Second derivative (per point²)"
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
    file_rows = tables["Replicate Diagnosis"]
    concise = ["Replicate ID", "File Name", "File Diagnosis", "Recommended decision",
               "Manual decision", "Decision source", "Min similarity (%)",
               "Recommendation reason"]
    review_editor(file_rows.loc[file_rows["Sample ID"] == sample, concise],
                  "sample", tables["File QC"])
    st.subheader("Review decision")
    name = st.selectbox("Exact OPUS file", filenames)
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
st.subheader("Batch review decisions")
st.caption(
    "Apply recommendations only to files without existing decisions: keep agreeing scans, "
    "recommend rescanning a uniquely suspected third scan. Ambiguous and invalid inputs "
    "stay pending. This never changes or deletes original spectra."
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
if st.session_state.get("qc_review_notice"):
    st.success(st.session_state.pop("qc_review_notice"))
with st.expander("All files and unresolved inputs"):
    file_table = tables["File QC"]
    selected = st.multiselect(
        "Filter file diagnosis",
        ["Consistent", "Suspected", "Needs review", "Invalid", "Unmatched"],
        default=["Consistent", "Suspected", "Needs review", "Invalid", "Unmatched"],
    )
    show_pending = st.checkbox("Pending decisions only")
    display = file_table.loc[file_table["File Diagnosis"].isin(selected)]
    if show_pending:
        display = display.loc[display["Manual decision"] == "Pending review"]
    detailed = st.checkbox("Show detailed metrics and error messages")
    columns = [
        "Sample ID", "Replicate ID", "File Name", "File Diagnosis", "Recommended decision",
        "Manual decision", "Decision source", "Recommendation reason",
    ]
    review_editor(display if detailed else display.reindex(columns=columns),
                  "all_files", file_table)
with st.expander("Exploratory MAD thresholds"):
    st.dataframe(tables["Threshold diagnostics"], hide_index=True)
st.subheader("Export QC results")
timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
agreed_tab, review_tab, rescan_tab = st.tabs(["Agreed spectra", "Review decisions", "Rescan list"])
with agreed_tab:
    agreed = tables["Agreed Spectra"]
    st.caption(
        "Automatic recommendation, not an approved PLSR selection. Includes all-pass groups "
        "and the unique passing pair of a complete triplet. Manual decisions remain separate."
    )
    st.write(f"{len(agreed)} agreed spectra across {agreed['Sample ID'].nunique()} samples.")
    review_editor(agreed, "agreed", tables["File QC"])
    st.download_button("Export Agreed Spectra", agreed.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"Agreed_Spectra_{timestamp}.csv", mime="text/csv")
with review_tab:
    review = tables["Review decisions"]
    st.caption("Recorded manual or applied-recommendation decisions. Pending is not approval.")
    review_editor(review, "export_review", tables["File QC"])
    kept = review.loc[review["Manual decision"] == "Keep"]
    st.download_button("Export Reviewed Keep List", kept.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"Reviewed_Keep_{timestamp}.csv", mime="text/csv")
with rescan_tab:
    rescan = tables["Rescan List"]
    rescan_mode = st.radio("Rescan export", ["All", "Confirmed only", "Suggestions only"],
                           horizontal=True)
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
output = st.text_input("QC output directory", value=str(Path(directory).parent / "Spectral_QC"))
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

if data.unmatched:
    with st.expander("Resolve unmatched files for optional calibration"):
        unmatched_name = st.selectbox("Unmatched filename", data.unmatched)
        unmatched_reason = st.text_input("Reason for excluding unmatched file (optional)")
        if st.button("Confirm exclusion of unmatched file"):
            save_review_edits([{
                "File Name": unmatched_name, "Manual decision": "Exclude",
                "Manual reason": unmatched_reason,
            }], tables["File QC"])

st.subheader("Save or restore review")
st.caption("Review snapshots are local JSON files; no spectra are uploaded.")
restore = st.file_uploader("Restore QC manifest for the current input and criteria", type=["json"])
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

st.subheader("Optional: use reviewed spectra for calibration")
st.warning(
    "QC does not change PLSR inputs unless you explicitly freeze and select a manifest "
    "on the Run page. All pending non-passing files must be resolved."
)
st.markdown("**Export spectra by review decision**")
st.caption(
    "Copy original OPUS files only, with exact filenames and verified checksums. "
    "This uses saved decisions, not unconfirmed recommendations. Apply recommended "
    "decisions first if you want to export those files as Keep. Pending files are "
    "not approved for calibration. This export does not freeze a calibration manifest."
)
export_choices = st.multiselect(
    "Decisions to export", ["Keep", "Exclude", "Rescan required", "Pending review"],
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
st.divider()
min_retained = st.number_input("Minimum retained scans per sample", min_value=2, value=2)
allow_single = st.checkbox("Allow explicitly reviewed single-scan exceptions")
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
    "Confirm suggested Keep for passing groups and all recorded manual decisions"
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
        st.session_state.qc_saved_folder = str(folder)
        st.success(f"Frozen manifest: {path}")
    except Exception as exc:
        st.error(str(exc))
if st.session_state.get("qc_frozen"):
    st.code(st.session_state.qc_frozen)
    st.caption("Select this manifest explicitly on the Run page.")
