from __future__ import annotations

from pathlib import Path

from soil_mir.reporting import (
    create_run_directory,
    export_validation_comparison,
    export_validation_result,
    finalize_run_manifest,
    initialize_run_manifest,
    read_run_manifest,
    record_run_failure,
    record_run_result,
    resume_run_manifest,
    write_json,
)
from soil_mir.services.calibration import (
    run_validation_analysis,
)
from soil_mir.services.history import (
    load_saved_run,
    pending_run_keys,
)
from soil_mir.validation import RunCancelled


def _cancelled(
    cancel_event,
) -> bool:
    return bool(
        cancel_event is not None
        and cancel_event.is_set()
    )


def _emit(
    callback,
    progress: float,
    message: str,
) -> None:
    if callback is not None:
        callback(
            max(
                0.0,
                min(
                    float(progress),
                    1.0,
                ),
            ),
            str(message),
        )


def execute_validation_run(
    *,
    datasets: dict,
    properties: list[str],
    methods: list[str],
    settings: dict,
    spectra_dir: str,
    reference_excel: str,
    output_dir: str,
    reference_ranges: dict,
    fallback_exclude_co2: bool,
    resume_run_dir: str | Path | None = None,
    cancel_event=None,
    progress_callback=None,
) -> dict:
    """Execute a validation run without Streamlit calls.

    Completed property/method artifacts are checkpointed immediately. A cancel
    request stops at a safe boundary and leaves the run resumable.
    """
    run_dir = None
    try:
        if resume_run_dir:
            run_dir = Path(
                resume_run_dir
            )
            manifest = resume_run_manifest(
                run_dir
            )
            results = (
                load_saved_run(manifest)
                if manifest.get("results")
                else {}
            )
        else:
            run_dir = create_run_directory(
                output_dir
            )
            initialize_run_manifest(
                run_dir,
                properties=properties,
                methods=methods,
                spectra_dir=spectra_dir,
                reference_excel=reference_excel,
            )
            write_json(
                run_dir / "Run_Config.json",
                {
                    "properties": properties,
                    "methods": methods,
                    "spectra_dir": spectra_dir,
                    "reference_excel": (
                        reference_excel
                    ),
                    "output_dir": output_dir,
                    "analysis_settings": (
                        settings
                    ),
                    "reference_ranges": (
                        reference_ranges
                    ),
                    "fallback_exclude_co2": bool(
                        fallback_exclude_co2
                    ),
                },
            )
            results = {}

        requested_pairs = [
            (
                property_sheet,
                method,
            )
            for property_sheet in properties
            for method in methods
        ]
        pending_pairs = [
            pair
            for pair in requested_pairs
            if (
                f"{pair[0]}::{pair[1]}"
                not in results
            )
        ]

        if not pending_pairs:
            comparison_path = (
                export_validation_comparison(
                    results,
                    run_dir,
                )
                if results
                else ""
            )
            finalize_run_manifest(
                run_dir,
                status="completed",
            )
            return {
                "status": "completed",
                "results": results,
                "run_dir": str(run_dir),
                "comparison_path": (
                    comparison_path
                ),
                "pending": [],
                "message": (
                    "Run already complete."
                ),
            }

        total = len(pending_pairs)
        completed = 0
        failed_count = 0

        for property_sheet in properties:
            property_pending = [
                method
                for method in methods
                if (
                    property_sheet,
                    method,
                )
                in pending_pairs
            ]
            if not property_pending:
                continue

            dataset = datasets[
                property_sheet
            ]
            for method in property_pending:
                if _cancelled(
                    cancel_event
                ):
                    raise RunCancelled(
                        "Validation cancelled by user."
                    )

                _emit(
                    progress_callback,
                    completed / total,
                    (
                        f"{property_sheet} / {method}: "
                        "starting nested validation"
                    ),
                )

                def method_progress(
                    step,
                    step_total,
                    message,
                    property_name=property_sheet,
                    method_name=method,
                ):
                    within = (
                        step / step_total
                        if step_total
                        else 0.0
                    )
                    _emit(
                        progress_callback,
                        (
                            completed
                            + within
                        )
                        / total,
                        (
                            f"{property_name} / "
                            f"{method_name}: {message}"
                        ),
                    )

                try:
                    result = run_validation_analysis(
                        dataset,
                        method=method,
                        **settings,
                        progress_callback=(
                            method_progress
                        ),
                        cancel_event=(
                            cancel_event
                        ),
                    )
                    if _cancelled(
                        cancel_event
                    ):
                        raise RunCancelled(
                            "Validation cancelled by user."
                        )
                    result["artifacts"] = (
                        export_validation_result(
                            result,
                            run_dir,
                        )
                    )
                    record_run_result(
                        run_dir,
                        result,
                        result["artifacts"],
                    )
                    results[
                        f"{property_sheet}::{method}"
                    ] = result
                except RunCancelled:
                    raise
                except Exception as exc:
                    failed_count += 1
                    record_run_failure(
                        run_dir,
                        property_name=(
                            property_sheet
                        ),
                        method=method,
                        error=str(exc),
                    )
                    _emit(
                        progress_callback,
                        completed / total,
                        (
                            f"{property_sheet} / {method} "
                            f"failed: {exc}"
                        ),
                    )
                finally:
                    completed += 1

                _emit(
                    progress_callback,
                    completed / total,
                    (
                        f"Finished {completed}/{total} "
                        "pending analysis combination(s)"
                    ),
                )

        manifest = read_run_manifest(
            run_dir
        )
        still_pending = sorted(
            pending_run_keys(
                manifest
            )
        )
        comparison_path = (
            export_validation_comparison(
                results,
                run_dir,
            )
            if results
            else ""
        )

        if not results:
            status = "failed"
            message = (
                "Every selected analysis failed."
            )
        elif still_pending:
            status = (
                "completed_with_errors"
            )
            message = (
                f"{len(still_pending)} analysis "
                "combination(s) remain pending."
            )
        else:
            status = "completed"
            message = "Run complete."

        finalize_run_manifest(
            run_dir,
            status=status,
            error=(
                message
                if status == "failed"
                else ""
            ),
        )
        _emit(
            progress_callback,
            1.0,
            message,
        )
        return {
            "status": status,
            "results": results,
            "run_dir": str(run_dir),
            "comparison_path": (
                comparison_path
            ),
            "pending": still_pending,
            "failed_count": failed_count,
            "message": message,
        }

    except RunCancelled:
        if run_dir is None:
            raise
        manifest = read_run_manifest(
            run_dir
        )
        still_pending = sorted(
            pending_run_keys(
                manifest
            )
        )
        results = (
            load_saved_run(manifest)
            if manifest.get("results")
            else {}
        )
        comparison_path = (
            export_validation_comparison(
                results,
                run_dir,
            )
            if results
            else ""
        )
        finalize_run_manifest(
            run_dir,
            status="cancelled",
            error=(
                "Cancelled by user at a safe checkpoint."
            ),
        )
        _emit(
            progress_callback,
            1.0,
            (
                "Cancellation complete. "
                "Saved results were preserved."
            ),
        )
        return {
            "status": "cancelled",
            "results": results,
            "run_dir": str(run_dir),
            "comparison_path": (
                comparison_path
            ),
            "pending": still_pending,
            "message": (
                "Cancelled by user at a safe checkpoint."
            ),
        }
    except Exception as exc:
        if run_dir is not None:
            try:
                finalize_run_manifest(
                    run_dir,
                    status="failed",
                    error=str(exc),
                )
            except Exception:
                pass
        raise
