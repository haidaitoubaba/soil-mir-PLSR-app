"""Run the existing Cleanup review steps on an independent session copy."""

from copy import copy
from datetime import datetime
from pathlib import Path

from .desktop_session import AUTO_COMMENT, record_history, write_snapshot
from .offline import offline_html


def already_reviewed(prop):
    for state in (prop, *prop.get("archive", [])):
        if (
            state.get("diagnostics", {}).keys() & {"A", "B"}
            or any(row.get("stage") in ("A", "B") for row in state.get("decisions", {}).values())
            or any(state.get("finished", {}).values())
        ):
            return True
    return False


def review_options(review):
    properties = review.state["properties"]
    return [
        {
            "property": name,
            "skip": already_reviewed(prop),
            "stage": "B"
            if prop["diagnostics"].get("B") and review.half_state(prop, "B")
            else "A"
            if prop["diagnostics"].get("A") and review.half_state(prop, "A")
            else "PCA",
        }
        for name, prop in properties.items()
    ]


def prepare_batch(review, selected, output):
    if (
        not isinstance(selected, list)
        or not selected
        or not all(isinstance(name, str) for name in selected)
    ):
        raise ValueError("Select at least one property.")
    if not set(selected) <= review.state["properties"].keys():
        raise ValueError("Select properties in the current session.")
    if not isinstance(output, str) or not output.strip():
        raise ValueError("Enter an existing output folder for the automatic cleanup copy.")
    parent = Path(output.strip()).expanduser().resolve(strict=True)
    if not parent.is_dir() or parent.is_relative_to(review.source):
        raise ValueError("Choose an existing output folder outside this session.")
    entries = [
        {
            "property": name,
            "status": "skipped"
            if already_reviewed(prop)
            else "queued"
            if name in selected
            else "not-selected",
        }
        for name, prop in review.state["properties"].items()
    ]
    if not any(row["status"] == "queued" for row in entries):
        raise ValueError("Select a property without previous Half A or Half B work.")
    return parent, entries


def process_property(review, name, progress):
    def apply(kind, stage, **fields):
        review.apply(
            {"kind": kind, "stage": stage, "property": name, "revision": review.revision, **fields}
        )

    review.select(name)
    progress("PCA")
    prop = review.state["properties"][name]
    if prop["pca_dirty"]:
        apply("refit", "PCA")
    if not prop["pca_done"]:
        apply("finish", "PCA")

    counts = {}
    for half in ("A", "B"):
        progress(f"Half {half}")
        apply(f"calculate-{half.lower()}", half)
        prop = review.state["properties"][name]
        candidates = [
            row for row in prop["diagnostics"][half]["rows"] if row["Concentration Candidate"]
        ]
        files = [row["File Name"] for row in candidates]
        before = set(prop["decisions"])
        if files:
            apply(
                "exclude",
                half,
                files=files,
                reason="concentration",
                unit="sample",
                comment=AUTO_COMMENT + ", ".join(files),
            )
        apply(f"finish-{half.lower()}", half)
        decisions = review.state["properties"][name]["decisions"]
        counts[half] = {
            "candidate_spectra": len(files),
            "samples": len({str(row["Sample"]) for row in candidates}),
            "excluded_spectra": len(decisions.keys() - before),
        }
    return counts


def run_batch(source, parent, results, progress, stopped):
    # Review actions replace the changed property's nested values, so the copy
    # shares read-only data until a property commits successfully.
    review = copy(source)
    review.state = {**source.state, "properties": dict(source.state["properties"])}
    review.undo = {}
    review.last_export = review.export_revision = None
    results = [dict(row) for row in results]
    report = {"results": results, "in_progress": True, "stopped": False}
    review.state["auto_cleanup"] = report
    record_history(review.state, "Automatic cleanup copy created (web)")
    target = parent / datetime.now().strftime("auto_cleanup_%Y%m%d_%H%M%S_%f")
    progress(
        {
            "message": "Saving an independent session copy…",
            "results": [dict(row) for row in results],
        }
    )
    review.source = review.save_as(str(target))
    review.saved_path = None
    review.suggested_path = review.destination_suggestion()

    queued = [row for row in results if row["status"] == "queued"]
    try:
        for index, row in enumerate(queued, 1):
            if stopped():
                break
            name = row["property"]
            original = review.state["properties"][name]
            history, revision = review.state["history"], review.revision

            def step(stage):
                progress(
                    {
                        "message": f"{index} / {len(queued)} · {name} · {stage}",
                        "property": name,
                        "stage": stage,
                        "path": str(target),
                        "results": [dict(item) for item in results],
                    }
                )

            try:
                counts = process_property(review, name, step)
            except (ValueError, ArithmeticError, OSError) as exc:
                review.state["properties"][name] = original
                review.state["history"], review.revision = history, revision
                row.update(status="failed", error=str(exc))
            else:
                row.update(status="completed", counts=counts)
            review.undo.pop(name, None)
            record_history(review.state, f"{name}: automatic cleanup {row['status']} (web)")
            write_snapshot(target, review.state)
        report.update(
            in_progress=False,
            stopped=stopped() and any(row["status"] == "queued" for row in queued),
        )
        for row in queued:
            if row["status"] == "queued":
                row["status"] = "not-run"
        review.active = source.active
        review.changed = False
        viewer = target / "PCA_viewer.html"
        replacement = viewer.with_suffix(".tmp")
        try:
            replacement.write_text(
                offline_html(review.all_property_data(), review.active), encoding="utf-8"
            )
            replacement.replace(viewer)
        finally:
            replacement.unlink(missing_ok=True)
        record_history(
            review.state,
            "Automatic cleanup stopped (web)"
            if report["stopped"]
            else "Automatic cleanup finished (web)",
        )
        write_snapshot(target, review.state)
    except Exception as exc:
        raise ValueError(f"Automatic cleanup stopped. Saved copy: {target}. {exc}") from exc
    return review
