"""Publish an independent export from confirmed desktop-format review decisions."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import posixpath
from pathlib import Path, PurePosixPath
import re
import tempfile
import zipfile
from xml.etree import ElementTree

from lxml import etree
import pandas as pd

from .desktop_session import fingerprint
from .export_figures import write_figures
from .offline import offline_html


SHEET_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
KEYS = ["Property", "File Name"]
HISTORICAL_COLUMNS = [
    *KEYS,
    "Sample",
    "Historical Excluded",
    "Python Excluded",
    "Comparison",
    "Historical Reason",
]


def source_workbook(state, supplied=None):
    path = Path(supplied or state.get("source", "")).expanduser().resolve()
    if not path.is_file():
        raise ValueError("Locate the original reference workbook before exporting.")
    if fingerprint(path) != state["source_sha256"]:
        raise ValueError("The selected workbook does not match the original SHA-256 fingerprint.")
    return path


def property_status(review, name, prop):
    spectra = len(prop["frame"])
    excluded = prop["decisions"]
    samples = len({row["Sample"] for row in prop["frame"] if row["File Name"] in excluded})
    if prop["pca_dirty"] or not prop["pca_done"]:
        status = "Finish PCA review"
    elif not prop["finished"]["A"] or not prop["diagnostics"].get("A"):
        status = "Finish Half A review"
    elif not prop["finished"]["B"] or not prop["diagnostics"].get("B"):
        status = "Finish Half B review"
    else:
        status = "Ready"
        try:
            review.validate_limit(prop, excluded, name)
        except ValueError as exc:
            status = str(exc)
    return {
        "property": name,
        "status": status,
        "total": spectra,
        "retained": spectra - len(excluded),
        "excluded": len(excluded),
        "affectedSamples": samples,
    }


def overview(review):
    rows = [
        property_status(review, name, prop) for name, prop in review.state["properties"].items()
    ]
    source_error = ""
    try:
        source_workbook(review.state)
    except (ValueError, OSError) as exc:
        source_error = str(exc)
    return {
        "rows": rows,
        "source": review.state["source"],
        "sourceError": source_error,
        "ready": bool(rows) and not source_error and all(row["status"] == "Ready" for row in rows),
        "parent": str(review.source.parent),
        "reviewPath": str(
            review.source.parent
            / ("review_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".xlsx")
        ),
        "lastExport": str(review.last_export) if review.export_revision == review.revision else "",
    }


def read_workbook(path):
    return pd.read_excel(path, sheet_name=None, engine="openpyxl")


def worksheet_paths(book):
    workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    targets = {row.attrib["Id"]: row.attrib["Target"] for row in rels}
    return {
        sheet.attrib["name"]: target.lstrip("/")
        if target.startswith("/")
        else posixpath.normpath(str(PurePosixPath("xl") / target))
        for sheet in workbook.findall("m:sheets/m:sheet", SHEET_NS)
        for target in [targets[sheet.attrib[REL_ID]]]
    }


def remove_worksheet_rows(xml, prop, removed):
    root = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    if root.findall(".//m:f", SHEET_NS):
        raise ValueError(
            f"{prop}: formulas in an affected worksheet require manual review before row deletion."
        )
    data = root.find("m:sheetData", SHEET_NS)
    remaining_offsets = iter(sorted(removed))
    next_removed = next(remaining_offsets, None)
    offset = 0
    for row in list(data):
        original_row = int(row.attrib["r"])
        while next_removed is not None and next_removed < original_row:
            offset += 1
            next_removed = next(remaining_offsets, None)
        if original_row in removed:
            data.remove(row)
            continue
        new_row = str(original_row - offset)
        row.attrib["r"] = new_row
        for cell in row:
            if "r" in cell.attrib:
                cell.attrib["r"] = re.sub(r"\d+$", new_row, cell.attrib["r"])
    for tag in ("dimension", "autoFilter"):
        node = root.find("m:" + tag, SHEET_NS)
        if node is not None and "ref" in node.attrib:
            node.attrib["ref"] = re.sub(
                r"\d+$",
                lambda match: str(max(1, int(match[0]) - len(removed))),
                node.attrib["ref"],
            )
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


def write_cleaned_workbook(source, out, frames, exclusions):
    removed = {}
    for prop, files in exclusions.items():
        if prop not in frames or "File Name" not in frames[prop]:
            raise ValueError(f"{prop}: original worksheet or File Name column is missing.")
        ids = frames[prop]["File Name"]
        unknown = files - set(ids)
        if unknown:
            raise ValueError(
                f"{prop}: exclusion filenames missing from source: {sorted(unknown)[:5]}"
            )
        if files:
            # Header is row 1. read_excel retains interior empty rows.
            removed[prop] = {int(i) + 2 for i in ids.index[ids.isin(files)]}

    with zipfile.ZipFile(source) as book:
        paths = worksheet_paths(book)
        patched = {
            paths[prop]: remove_worksheet_rows(book.read(paths[prop]), prop, rows)
            for prop, rows in removed.items()
        }
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as cleaned:
            for member in book.infolist():
                data = patched[member.filename] if member.filename in patched else book.read(member)
                cleaned.writestr(member, data)

    actual = read_workbook(out)
    if list(actual) != list(frames):
        raise ValueError("Excel verification failed: worksheet names or order changed.")
    for prop, before in frames.items():
        expected = before
        if files := exclusions.get(prop):
            expected = before.loc[~before["File Name"].isin(files)].reset_index(drop=True)
        try:
            pd.testing.assert_frame_equal(
                actual[prop], expected, check_exact=True, check_dtype=False
            )
        except AssertionError as exc:
            raise ValueError(
                f"{prop}: the saved worksheet differs from its expected retained rows."
            ) from exc


def review_table(state):
    all_rows = []
    for prop, saved in state["properties"].items():
        for row in saved["frame"]:
            decision = saved["decisions"].get(row["File Name"])
            stage = saved["halves"].get(row["Sample"], "PCA") if saved["pca_done"] else "PCA"
            all_rows.append(
                {
                    **row,
                    "Property": prop,
                    "Confirm": "YES" if decision else "",
                    "Reason": decision["reason"] if decision else "",
                    "Unit": decision["unit"]
                    if decision
                    else ("sample" if stage in {"A", "B"} else "spectrum"),
                    "Comment": decision["comment"] if decision else "",
                    "Stage": decision["stage"] if decision else stage,
                }
            )
    return pd.DataFrame(all_rows)


def write_review_workbook(state, destination, review):
    instructions = [
        "Review covers every original record of the selected properties. "
        "YES is a confirmed exclusion.",
        "Property and File Name identify a reviewed record. "
        "Stage gives the current review or exclusion stage.",
        "Unit indicates the decision scope. Reason and Comment may be blank.",
        "Calibration A and B show the saved diagnostic fits. "
        "A candidate remains included until confirmed.",
    ]
    with pd.ExcelWriter(destination, engine="openpyxl") as writer:
        review.to_excel(writer, sheet_name="Review", index=False)
        for half in ("A", "B"):
            rows = [
                {**row, "Property": prop}
                for prop, saved in state["properties"].items()
                for row in saved["diagnostics"].get(half, {}).get("rows", [])
            ]
            pd.DataFrame(rows).to_excel(writer, sheet_name=f"Calibration {half}", index=False)
        pd.DataFrame({"Instructions": instructions}).to_excel(
            writer, sheet_name="Read Me", index=False
        )
        for sheet in writer.book.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        cell.data_type = "s"

    columns = [*KEYS, "Confirm", "Reason", "Unit", "Comment", "Stage"]
    expected = ["Review", "Calibration A", "Calibration B", "Read Me"]
    with pd.ExcelFile(destination, engine="openpyxl") as saved:
        if saved.sheet_names != expected:
            raise ValueError("Review Excel verification failed: worksheet layout changed.")
        actual = saved.parse("Review", keep_default_na=False, dtype=str)[columns]
    expected_rows = review[columns].fillna("").astype(str)
    try:
        pd.testing.assert_frame_equal(actual, expected_rows, check_dtype=False)
    except AssertionError as exc:
        raise ValueError(
            "Review Excel verification failed: an identity or decision differs."
        ) from exc


def safe_parent(path, review):
    if not path.strip():
        raise ValueError("Choose a local output location.")
    parent = Path(path).expanduser().resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("Choose an existing folder.")
    if parent.is_relative_to(review.source):
        raise ValueError("Choose an output folder outside the original session.")
    return parent


def export_review_only(review, path):
    requested = Path(path.strip()).expanduser()
    parent = safe_parent(str(requested.parent), review)
    target = parent / requested.name
    if target.suffix.lower() != ".xlsx" or target.exists():
        raise ValueError("Choose a new .xlsx file for the review export.")
    with tempfile.TemporaryDirectory(prefix=".mir-review-", dir=parent) as stage:
        prepared = Path(stage) / "review.xlsx"
        write_review_workbook(review.state, prepared, review_table(review.state))
        try:
            os.link(prepared, target)
        except FileExistsError as exc:
            raise ValueError("The review output already exists. Choose a new filename.") from exc
    return target


def historical_comparison(frames, exclusions):
    rows = []
    for prop, files in exclusions.items():
        prior = frames.get(prop + "_OPUS")
        if prior is None:
            continue
        originals = frames[prop].dropna(how="all")
        historic = prior.dropna(how="all")
        for frame in (originals, historic):
            if (
                "File Name" not in frame
                or frame["File Name"].isna().any()
                or frame["File Name"].duplicated().any()
            ):
                raise ValueError(
                    f"{prop}: historical comparison requires unique, nonblank File Name values."
                )
        ids = set(historic["File Name"])
        if not ids <= set(originals["File Name"]):
            raise ValueError(f"{prop}: historical sheet contains unknown filenames.")
        for row in originals.to_dict("records"):
            file = row["File Name"]
            old, new = file not in ids, file in files
            rows.append(
                {
                    "Property": prop,
                    "Sample": row["Sample"],
                    "File Name": file,
                    "Historical Excluded": old,
                    "Python Excluded": new,
                    "Comparison": "both"
                    if old and new
                    else "historical only"
                    if old
                    else "Python only"
                    if new
                    else "neither",
                    "Historical Reason": "unverified" if old else "",
                }
            )
    return pd.DataFrame(rows, columns=HISTORICAL_COLUMNS)


def json_file(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def export_cleaned(review, parent_path):
    state = review.state
    for name, prop in state["properties"].items():
        status = property_status(review, name, prop)["status"]
        if status != "Ready":
            raise ValueError(f"{name}: {status}.")
    original = source_workbook(state)
    parent = safe_parent(parent_path, review)
    generated = datetime.now().astimezone()
    destination = parent / generated.strftime("cleanup_export_%Y%m%d_%H%M%S_%f")
    exclusions = {name: set(prop["decisions"]) for name, prop in state["properties"].items()}
    rows = review_table(state)
    audit = rows.loc[rows["Confirm"].eq("YES")].rename(columns={"Reason": "Reasons"})
    properties = review.all_property_data()

    with tempfile.TemporaryDirectory(prefix=".mir-export-", dir=parent) as temporary:
        stage = Path(temporary) / "ready"
        stage.mkdir()
        cleaned = stage / "reference_cleaned.xlsx"
        frames = read_workbook(original)
        write_cleaned_workbook(original, cleaned, frames, exclusions)
        write_review_workbook(state, stage / "review.xlsx", rows)
        audit.to_csv(stage / "confirmed_audit.csv", index=False)
        historical_comparison(frames, exclusions).to_csv(
            stage / "historical_comparison.csv", index=False
        )
        (stage / "PCA_viewer.html").write_text(
            offline_html(properties, review.active), encoding="utf-8"
        )
        write_figures(state, properties, stage)

        provenance = {
            "source": str(original),
            "source_sha256": state["source_sha256"],
            "properties": list(state["properties"]),
            "cleaned_sha256": fingerprint(cleaned),
            "confirmed_exclusions": audit.astype(object)
            .where(pd.notna(audit), None)
            .to_dict("records"),
            "concentration_limit": state["limit"],
            "concentration_limit_percent": state["percent"],
            "settings": {name: prop["config"] for name, prop in state["properties"].items()},
            "opus_axis_mode": state.get("opus_axis_mode"),
            "method": (
                "Sequential PCA review, A calibration review, B reuses A preprocessing "
                "and selection rank on retained A."
            ),
            "exported_at": generated.astimezone(timezone.utc).isoformat(),
        }
        json_file(cleaned.with_suffix(".cleanup.json"), provenance)
        json_file(stage / "session_audit.json", state)
        source_workbook(state)
        if destination.exists():
            raise ValueError("The generated export directory already exists. Retry export.")
        stage.rename(destination)

    review.last_export = destination
    review.export_revision = review.revision
    return destination
