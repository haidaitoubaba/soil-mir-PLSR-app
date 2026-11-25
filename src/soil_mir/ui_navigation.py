"""Native, local navigation definitions for RC7."""
from __future__ import annotations

import inspect

import streamlit as st


# Material Symbols are shipped by Streamlit, not fetched from an external CDN.
PAGES = (
    ("home", "Home", None, "home"),
    ("data", "Data", "pages/1_Data.py", "database"),
    ("qc", "Spectral QC", "pages/1_Spectral_QC.py", "document_scanner"),
    ("configuration", "Configuration", "pages/2_Configuration.py", "tune"),
    ("run", "Run", "pages/3_Run.py", "play_circle"),
    ("results", "Results", "pages/4_Results.py", "monitoring"),
    ("predict", "Predict", "pages/5_Predict.py", "my_location"),
    ("history", "Run History", "pages/6_Run_History.py", "history"),
)

ICONS = {
    "Input Data": "folder_open",
    "Data Overview": "dashboard",
    "Data Acceptance": "verified_user",
    "Setup": "settings",
    "Overview": "dashboard",
    "Diagnostics": "monitoring",
    "Review": "fact_check",
    "Export": "download",
    "Calibration": "science",
    "General": "settings",
    "Validation": "verified_user",
    "Preprocessing": "waves",
    "Advanced": "tune",
    "Profiles": "bookmark",
    "Preflight": "checklist",
    "Execution": "play_arrow",
    "Summary": "task",
    "Model Selection": "my_location",
    "Detailed Results": "table_chart",
    "Model": "layers",
    "Compatibility": "verified_user",
    "Prediction": "play_arrow",
    "Results": "bar_chart",
    "Run Library": "library_books",
    "Run Details": "description",
    "Saved Models": "layers",
    "Management": "settings",
}


def material(name):
    return f":material/{name}:"


def section_key(page, section):
    return f"rc7_nav_{page}_{section}"


def tile_label(label, icon, selected=False):
    """Use supported Markdown hard breaks; no DOM selectors or custom JS."""
    return f"{material(icon)}  \n" + (f"**{label}**" if selected else label)


def tile_button(container, label, icon, *, key, selected, on_click=None, args=()):
    kwargs = {
        "key": key, "help": label, "type": "primary" if selected else "secondary",
        "use_container_width": True, "on_click": on_click, "args": args,
    }
    # Older supported Streamlit versions wrap labels by default.
    if "wrap" in inspect.signature(st.button).parameters:
        kwargs["wrap"] = True
    return container.button(tile_label(label, icon, selected), **kwargs)


def render_sidebar(home):
    """Register the original page paths; render a single native page-link menu."""
    pages = [
        (identifier, title, st.Page(home if path is None else path, title=title,
                                    default=path is None), icon)
        for identifier, title, path, icon in PAGES
    ]
    active = st.navigation([page for _, _, page, _ in pages], position="hidden")
    with st.sidebar:
        st.markdown(f"### {material('eco')} Soil MIR PLSR")
        st.caption("Workspace")
        for identifier, title, page, icon in pages:
            if identifier == "history":
                st.divider()
            # Native page links handle active-page styling and routing.
            st.page_link(page, label=title, icon=material(icon),
                         help=title, use_container_width=True)
        st.divider()
        st.caption(f"{material('hard_drive')} Local workspace")
    return active
