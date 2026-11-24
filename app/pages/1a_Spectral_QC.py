from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import io
import json

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from soil_mir.io.opus import list_opus_files
from soil_mir.qc import Criteria, REGIONS, group_issues
from soil_mir.services.local_paths import choose_local_path, open_local_folder
from soil_mir.services.spectral_qc import (
    evaluate_batch, file_inventory, prepare_batch, report_bytes,
)

from soil_mir.services.qc_manifest import (
    build_manifest, criteria_from_dict, read_mapping, resolve_groups,
    review_selection, save_manifest, validate_manifest,
)

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
a, b = st.columns(2)
lower = a.number_input("QC minimum (cm⁻¹)", value=600., format="%.4f")
upper = b.number_input("QC maximum (cm⁻¹)", value=4000., format="%.4f")
exclude_co2 = st.checkbox("Exclude CO₂ from global metrics (retain regional diagnostic)")
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
          exclude_co2, regions, mapping)
if st.button("Run QC", type="primary", disabled=not names):
    progress = st.progress(0., text="Reading spectra")
    try:
        data = prepare_batch(
            directory, pattern=pattern, batch_label=batch_label, expected=expected,
            lower=lower, upper=upper, exclude_co2=exclude_co2, regions=regions,
            cache_root=Path.home() / ".soil_mir_app" / "qc_cache",
            progress=lambda fraction, message: progress.progress(fraction, text=message),
            mapping=mapping,
        )
        st.session_state.qc_data = data
        st.session_state.qc_config = config
        st.session_state.qc_reviews = {}
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
    st.session_state.pop("qc_frozen", None)
    st.session_state.qc_review_criteria = criteria
    st.info("Threshold changed: cached metrics reused; review decisions require reconfirmation.")
tables = evaluate_batch(data, criteria, st.session_state.qc_reviews)
overview = tables["Overview"].set_index("Metric")["Value"]
st.subheader("QC summary")
for col, key in zip(st.columns(4), ["Pass", "Review", "Fail", "Incomplete"]):
    col.metric(key, int(overview[key]))
st.caption(
    f"Identified samples: {int(overview['Identified samples'])}; "
    f"unmatched files: {int(overview['Unmatched files'])}; "
    f"read errors: {int(overview['Read errors'])}. Pass rate uses all identified samples."
)
if pd.notna(overview["Sample pass rate (%)"]):
    st.metric("Sample pass rate", f"{overview['Sample pass rate (%)']:.2f}%")
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
    pair_frame = tables["Pairwise QC"]
    if not pair_frame.empty:
        st.dataframe(pair_frame.loc[pair_frame["Sample ID"] == sample], hide_index=True)
    regional_frame = tables["Regional QC"]
    if not regional_frame.empty:
        with st.expander("Regional QC"):
            st.dataframe(regional_frame.loc[regional_frame["Sample ID"] == sample],
                         hide_index=True)
    filenames = [scan.filename for scan in data.groups[sample]]
    visible = st.multiselect("Show spectra", filenames, default=filenames, key=f"qc_plot_{sample}")
    fig, ax = plt.subplots()
    for i, name in enumerate(filenames):
        if name in visible and name in data.raw:
            values, axis = data.raw[name]
            ax.plot(axis, values, label=name, color=f"C{i%10}",
                    linewidth=2 if name == sample_row["Suspected File"] else 1)
    ax.set_xlabel("Wavenumber (cm⁻¹)")
    ax.set_ylabel("Absorbance")
    ax.invert_xaxis()
    if ax.lines:
        ax.legend(fontsize="small")
    st.pyplot(fig)
    plt.close(fig)
    if sample in data.aligned:
        axis, spectra = data.aligned[sample]
        fig, ax = plt.subplots()
        for i, name in enumerate(filenames):
            for other in filenames[i+1:]:
                if name in visible and other in visible and name in spectra and other in spectra:
                    ax.plot(axis, spectra[name] - spectra[other], label=f"{name} - {other}")
        ax.axhline(0, color="gray", linewidth=.8)
        ax.invert_xaxis()
        ax.set_xlabel("Wavenumber (cm⁻¹)")
        ax.set_ylabel("Difference (AU)")
        if len(ax.lines) > 1:
            ax.legend(fontsize="small")
        st.pyplot(fig)
        plt.close(fig)
    file_rows = tables["Replicate Diagnosis"]
    st.dataframe(file_rows.loc[file_rows["Sample ID"] == sample], hide_index=True)
    st.subheader("Review decision")
    name = st.selectbox("Exact OPUS file", filenames)
    previous = st.session_state.qc_reviews.get(name, {})
    choices = ["Pending review", "Keep", "Exclude", "Rescan required"]
    with st.form(f"qc_review_{name}_{criteria}"):
        decision = st.radio("Decision", choices,
                            index=choices.index(previous.get("decision", choices[0])))
        reason = st.text_area("Reason", value=previous.get("reason", ""))
        if st.form_submit_button("Save review decision"):
            if decision != "Pending review" and not reason.strip():
                st.error("Enter a reason for this explicit decision.")
            else:
                st.session_state.pop("qc_frozen", None)
                st.session_state.qc_reviews[name] = {
                    "decision": decision, "reason": reason,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                st.rerun()
with st.expander("All files and unresolved inputs"):
    st.dataframe(tables["File QC"], hide_index=True)
with st.expander("Exploratory MAD thresholds"):
    st.dataframe(tables["Threshold diagnostics"], hide_index=True)
st.subheader("Export QC results")
rescan = tables["Rescan List"]
st.dataframe(rescan, hide_index=True)
rescan_mode = st.radio("Rescan export", ["All", "Confirmed only", "Suggestions only"],
                       horizontal=True)
if rescan_mode == "Confirmed only":
    rescan = rescan.loc[rescan["Type"] == "Confirmed rescan"]
elif rescan_mode == "Suggestions only":
    rescan = rescan.loc[rescan["Type"] != "Confirmed rescan"]
timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
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
        unmatched_reason = st.text_input("Reason for excluding unmatched file")
        if st.button("Confirm exclusion of unmatched file"):
            if not unmatched_reason.strip():
                st.error("Enter a reason.")
            else:
                st.session_state.qc_reviews[unmatched_name] = {
                    "decision": "Exclude", "reason": unmatched_reason,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                st.session_state.pop("qc_frozen", None)
                st.rerun()

st.subheader("Save or restore review")
st.caption("Review snapshots are local JSON files; no spectra are uploaded.")
restore = st.file_uploader("Restore QC manifest for the current input and criteria", type=["json"])
if restore and st.button("Restore saved review"):
    try:
        payload = json.loads(restore.getvalue())
        validate_manifest(payload, directory)
        current = {
            "directory": data.directory, "pattern": data.pattern, "batch_label": data.batch_label,
            "expected": data.expected, "lower": data.lower, "upper": data.upper,
            "exclude_co2": data.exclude_co2, "regions": [list(r) for r in data.regions],
            "mapping": data.mapping, "opus_axis_mode": "native_npt",
        }
        if payload["input"] != current or criteria_from_dict(payload["criteria"]) != criteria:
            raise ValueError("Input settings or thresholds differ from saved review.")
        st.session_state.qc_reviews = payload["decisions"]
        st.session_state.pop("qc_frozen", None)
        st.rerun()
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
