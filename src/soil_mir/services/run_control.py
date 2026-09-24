from __future__ import annotations

from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
)
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event

from soil_mir.services.run_execution import (
    execute_validation_run,
)


_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="soil-mir-validation",
)


@dataclass
class ValidationJob:
    future: Future
    cancel_event: Event
    events: Queue

    def request_cancel(
        self,
    ) -> None:
        self.cancel_event.set()

    @property
    def cancel_requested(
        self,
    ) -> bool:
        return self.cancel_event.is_set()

    def drain_events(
        self,
    ) -> list[dict]:
        drained = []
        while True:
            try:
                drained.append(
                    self.events.get_nowait()
                )
            except Empty:
                break
        return drained


def start_validation_job(
    **kwargs,
) -> ValidationJob:
    cancel_event = Event()
    events = Queue()

    def progress_callback(
        progress: float,
        message: str,
    ) -> None:
        events.put(
            {
                "progress": float(progress),
                "message": str(message),
            }
        )

    future = _EXECUTOR.submit(
        execute_validation_run,
        **kwargs,
        cancel_event=cancel_event,
        progress_callback=(
            progress_callback
        ),
    )
    return ValidationJob(
        future=future,
        cancel_event=cancel_event,
        events=events,
    )
