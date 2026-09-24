from threading import Event

from soil_mir.reporting import (
    read_run_manifest,
)
from soil_mir.services.run_execution import (
    execute_validation_run,
)


def test_cancelled_run_is_checkpointed_as_resumable(
    tmp_path,
):
    cancel_event = Event()
    cancel_event.set()

    result = execute_validation_run(
        datasets={
            "202_STC": object(),
        },
        properties=["202_STC"],
        methods=["kfold"],
        settings={},
        spectra_dir="/data/spectra",
        reference_excel="/data/reference.xlsx",
        output_dir=str(tmp_path),
        reference_ranges={},
        fallback_exclude_co2=False,
        cancel_event=cancel_event,
    )

    assert result["status"] == "cancelled"
    assert result["pending"] == [
        "202_STC::kfold"
    ]

    manifest = read_run_manifest(
        result["run_dir"]
    )
    assert manifest["status"] == "cancelled"
    assert manifest["results"] == []
    assert (
        manifest["error"]
        == "Cancelled by user at a safe checkpoint."
    )
