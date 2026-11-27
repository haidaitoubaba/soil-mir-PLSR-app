from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event
from zipfile import BadZipFile

import streamlit as st

from soil_mir.services.local_paths import choose_local_path, open_local_folder
from soil_mir.ui_state import request_section

from .auto_cleanup import prepare_batch, review_options, run_batch
from .dataset_export import export_cleaned, export_review_only, overview, source_workbook
from .desktop_session import DesktopReview, record_history
from .handoff import build_handoff
from .offline import offline_html
from .session_creation import create_session, inspect_inputs


UI = Path(__file__).with_name("workbench")
KEY = "pca_workbench"


def browse_local_path(field: str) -> str | None:
    prompts = {
        "workbook": ("file", "Choose the original reference Excel"),
        "spectra": ("directory", "Choose the OPUS spectra folder"),
        "output": ("directory", "Choose the Cleanup output folder"),
        "session": ("file", "Choose session.json in a saved Cleanup session folder"),
    }
    if field not in prompts:
        raise ValueError("Choose a valid path field.")
    kind, prompt = prompts[field]
    path = choose_local_path(kind, prompt=prompt)
    if path is not None and field == "session" and path.name != "session.json":
        raise ValueError("Choose the session.json file inside the saved Cleanup session folder.")
    return str(path) if path is not None else None


def change_session(desktop):
    st.session_state.cleanup_desktop = desktop
    st.session_state.cleanup_open_revision = st.session_state.get("cleanup_open_revision", 0) + 1


@st.cache_resource
def background_executor():
    return ThreadPoolExecutor(max_workers=1)


def import_action(event):
    kind = event["kind"]
    if st.session_state.get("cleanup_auto_job") is not None:
        raise ValueError("Wait for automatic cleanup to finish.")
    if kind == "new-poll":
        job = st.session_state.get("cleanup_import_job")
        if job is None:
            return
        future, updates = job
        st.session_state.cleanup_import_poll = event["poll"]
        while True:
            try:
                st.session_state.cleanup_import_progress = updates.get_nowait()
            except Empty:
                break
        if not future.done():
            return
        del st.session_state.cleanup_import_job
        review, warning = future.result()
        change_session(review)
        st.session_state.cleanup_import_feedback = {"created": str(review.source)}
        return f"Created Cleanup session at {review.source}.{warning}"
    if st.session_state.get("cleanup_import_job") is not None:
        raise ValueError("A Cleanup session is already being created.")
    if kind == "new-browse":
        field = event.get("field")
        path = browse_local_path(field)
        st.session_state.cleanup_import_feedback = {"field": field, "path": path}
        return
    paths = tuple(event.get(field) for field in ("workbook", "spectra", "output"))
    if kind == "new-inspect":
        st.session_state.pop("cleanup_import_inputs", None)
        inputs = inspect_inputs(*paths)
        st.session_state.cleanup_import_inputs = (paths, inputs)
        st.session_state.cleanup_import_feedback = {"preview": inputs.preview()}
        return
    if kind == "new-create":
        checked_paths, inputs = st.session_state.get("cleanup_import_inputs", (None, None))
        if paths != checked_paths:
            raise ValueError("Run Check inputs after changing any path.")
        updates = SimpleQueue()
        st.session_state.cleanup_import_progress = "Verifying the reference workbook…"
        st.session_state.cleanup_import_poll = 0
        future = background_executor().submit(
            create_session, inputs, event.get("selected"), updates.put
        )
        st.session_state.cleanup_import_job = (future, updates)
        return
    raise ValueError("Unknown new-session action.")


def auto_action(desktop, event):
    if desktop is None:
        raise ValueError("Open or create a Cleanup session first.")
    kind = event["kind"]
    job = st.session_state.get("cleanup_auto_job")
    if kind == "auto-poll":
        if job is None:
            return None
        job["poll"] = event["poll"]
        while True:
            try:
                job["progress"] = job["updates"].get_nowait()
            except Empty:
                break
        if not job["future"].done():
            return None
        del st.session_state.cleanup_auto_job
        result = job["future"].result()
        change_session(result)
        return f"Automatic cleanup copy saved to {result.source}"
    if kind == "auto-stop" and job is not None:
        job["stop"].set()
        return None
    if job is not None:
        raise ValueError("Automatic cleanup is already running.")
    if event.get("revision") != desktop.revision:
        raise ValueError(
            "The review changed. Reopen Auto Cleanup and check the selected properties."
        )
    if kind == "auto-browse":
        st.session_state.cleanup_auto_feedback = {"path": browse_local_path("output")}
        return None
    if kind == "auto-review":
        name, stage = event.get("name"), event.get("targetStage")
        option = next((item for item in review_options(desktop) if item["property"] == name), None)
        if option is None or stage not in {"PCA", option["stage"]} | (
            {"A"} if option["stage"] == "B" else set()
        ):
            raise ValueError(
                "That review stage is unavailable. Reopen Auto Cleanup and check the property."
            )
        desktop.select(name)
        st.session_state.cleanup_review_navigation = {
            "property": name,
            "stage": stage,
            "automatic": bool(event.get("automatic")),
        }
        return None
    if kind != "auto-start":
        raise ValueError("Unknown automatic cleanup action.")
    parent, entries = prepare_batch(desktop, event.get("selected"), event.get("path"))
    updates, stop = SimpleQueue(), Event()
    future = background_executor().submit(
        run_batch, desktop, parent, entries, updates.put, stop.is_set
    )
    st.session_state.cleanup_auto_job = {
        "future": future,
        "updates": updates,
        "stop": stop,
        "poll": 0,
        "progress": {"message": "Preparing automatic cleanup…", "results": entries},
    }
    return None


def execute_action(event):
    desktop = st.session_state.get("cleanup_desktop")
    kind = event.get("kind")
    if isinstance(kind, str) and kind.startswith("new-"):
        return import_action(event)
    if st.session_state.get("cleanup_import_job") is not None:
        raise ValueError("Wait for the new session to finish creating.")
    if isinstance(kind, str) and kind.startswith("auto-"):
        return auto_action(desktop, event)
    if st.session_state.get("cleanup_auto_job") is not None:
        raise ValueError("Wait for automatic cleanup to finish.")
    if kind == "browse-desktop":
        st.session_state.cleanup_desktop_pick = {"path": browse_local_path("session")}
        return None
    if kind == "open-desktop":
        path = str(event.get("path", "")).strip()
        if not path:
            raise ValueError("Enter a desktop Cleanup session folder or its session.json path.")
        incoming = DesktopReview(path)
        change_session(incoming)
        return "Desktop session opened. Save a copy to keep your review edits."
    if desktop is None:
        raise ValueError("Open or create a Cleanup session first.")
    if kind == "offline-viewer":
        st.session_state.cleanup_offline_document = {
            "requestId": event["requestId"],
            "html": offline_html(desktop.all_property_data(), event.get("property")),
        }
        return None
    if kind == "select-property":
        desktop.select(event.get("name"))
        return None
    if kind == "save-copy":
        path = desktop.save_as(str(event.get("path", "")))
        return f"Saved Cleanup review copy to {path}"
    if kind == "open-export-folder":
        folder = desktop.last_export
        if (
            folder is None
            or desktop.export_revision != desktop.revision
            or event.get("revision") != desktop.revision
        ):
            raise ValueError("Export the cleaned dataset first.")
        open_local_folder(folder)
        return "Opened the export folder."
    if kind == "use-in-plsr":
        if event.get("revision") != desktop.revision:
            raise ValueError("Export the current Cleanup review first.")
        spectra = event.get("path") or desktop.state.get("spectra_dir") or ""
        st.session_state.cleanup_pending_handoff = build_handoff(desktop, spectra)
        return None
    if kind in {"export-cleaned", "export-review", "locate-workbook"}:
        if event.get("revision") != desktop.revision:
            raise ValueError("The review changed. Recheck the current export overview.")
        path = str(event.get("path", "")).strip()
        if not path:
            raise ValueError("Enter the local path first.")
        if kind == "export-cleaned":
            return f"Exported cleaned dataset to {export_cleaned(desktop, path)}"
        if kind == "export-review":
            return f"Exported review Excel to {export_review_only(desktop, path)}"
        matching = source_workbook(desktop.state, path)
        if str(matching) != desktop.state["source"]:
            desktop.state["source"] = str(matching)
            record_history(desktop.state, "Relocated source workbook (web)")
            desktop.revision += 1
            desktop.changed = True
        return "Verified the original reference workbook."
    return desktop.apply(event)


def handle_action():
    event = st.session_state[KEY].action
    if not isinstance(event, dict):
        return
    try:
        message = execute_action(event)
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        ArithmeticError,
        SyntaxError,
        RuntimeError,
        BadZipFile,
    ) as exc:
        if str(event.get("kind", "")).startswith("new-"):
            st.session_state.cleanup_import_feedback = {"error": str(exc)}
        elif str(event.get("kind", "")).startswith("auto-"):
            st.session_state.cleanup_auto_feedback = {"error": str(exc)}
        elif event.get("kind") == "browse-desktop":
            st.session_state.cleanup_desktop_pick = {"error": str(exc)}
        else:
            st.session_state.cleanup_notice = {"message": str(exc), "error": True}
    else:
        if message:
            st.session_state.cleanup_notice = {"message": message, "error": False}
        following = {"finish": "A", "finish-a": "B", "finish-b": "Export"}.get(event["kind"])
        if following:
            st.session_state.cleanup_review_navigation = {
                "property": event["property"],
                "stage": following,
            }


def render_workbench() -> None:
    state = st.session_state
    if "cleanup_pending_handoff" in state:
        request_section("data", "Input Data")
        st.switch_page("pages/1_Data.py")

    st.title("Cleanup")
    applied = state.get("rc6_data_applied_paths")
    workbench = st.components.v2.component(
        "mir_cleanup_pca",
        html=(UI / "workbench.html").read_text(encoding="utf-8"),
        css=(UI / "workbench.css").read_text(encoding="utf-8"),
        js="\n".join(
            (UI / name).read_text(encoding="utf-8")
            for name in ("chart.mjs", "new-session.mjs", "auto-cleanup.mjs", "workbench.mjs")
        ),
    )

    notice = st.session_state.pop("cleanup_notice", None)
    desktop = st.session_state.get("cleanup_desktop")
    if desktop is None:
        data = {"mode": "empty", "notice": notice}
    else:
        data = desktop.workbench_data(notice)
        export_overview = overview(desktop)
        if export_overview["lastExport"]:
            spectra = desktop.state.get("spectra_dir") or ""
            needs_path = not spectra or not Path(spectra).expanduser().is_dir()
            export_overview["handoff"] = {
                "needsPath": needs_path,
                "path": applied[0] if needs_path and applied else spectra,
            }
        data["exportOverview"] = export_overview
        data["autoCleanup"] = {
            "properties": review_options(desktop),
            "parent": str(desktop.source.parent),
            "report": desktop.state.get("auto_cleanup"),
        }
    if applied:
        data["newSessionDefaults"] = dict(zip(("spectra", "workbook", "output"), applied))
    data["openRevision"] = st.session_state.get("cleanup_open_revision", 0)
    if navigation := st.session_state.pop("cleanup_review_navigation", None):
        data["reviewNavigation"] = navigation
    if document := st.session_state.pop("cleanup_offline_document", None):
        data["offlineDocument"] = document
    if st.session_state.get("cleanup_import_job") is not None:
        data["importProgress"] = {
            "message": st.session_state.cleanup_import_progress,
            "poll": st.session_state.cleanup_import_poll,
        }
    if feedback := st.session_state.pop("cleanup_import_feedback", None):
        data["importFeedback"] = feedback
    if picked := st.session_state.pop("cleanup_desktop_pick", None):
        data["desktopPick"] = picked
    if job := st.session_state.get("cleanup_auto_job"):
        data["autoProgress"] = {
            **job["progress"],
            "poll": job["poll"],
            "stopping": job["stop"].is_set(),
        }
    if feedback := st.session_state.pop("cleanup_auto_feedback", None):
        data["autoFeedback"] = feedback
    workbench(data=data, key=KEY, on_action_change=handle_action)
