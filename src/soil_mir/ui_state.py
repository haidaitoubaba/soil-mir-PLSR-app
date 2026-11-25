"""Shared UI navigation and durable widget values for the Streamlit pages."""
from copy import deepcopy

import streamlit as st

from soil_mir.ui_navigation import ICONS, section_key, tile_button


SECTIONS = {
    "data": ("Input Data", "Data Overview", "Data Acceptance"),
    "qc": ("Setup", "Overview", "Diagnostics", "Review", "Export", "Calibration"),
    "configuration": ("General", "Validation", "Preprocessing", "Advanced", "Profiles"),
    "run": ("Preflight", "Execution", "Summary"),
    "results": ("Overview", "Model Selection", "Diagnostics", "Detailed Results", "Export"),
    "predict": ("Model", "Input Data", "Compatibility", "Prediction", "Results"),
    "history": ("Run Library", "Run Details", "Saved Models", "Management"),
}


def valid_choice(value, options, default=None):
    """Resolve a stale selection without relying on the presentation label."""
    if value in options:
        return value
    if default in options:
        return default
    return options[0] if options else None


def request_section(page, section):
    """Request a navigation change before the next widget construction."""
    if section not in SECTIONS[page]:
        raise ValueError(f"Unknown section {page}: {section}")
    st.session_state[f"rc6_requested_section_{page}"] = section


def section_navigation(page):
    """Only callers' selected section should be rendered; preserve on return."""
    options = SECTIONS[page]
    saved = f"rc6_section_{page}"
    requested = st.session_state.pop(f"rc6_requested_section_{page}", None)
    current = valid_choice(
        requested if requested is not None else st.session_state.get(saved), options
    )
    st.session_state[saved] = current

    def select(value):
        st.session_state[saved] = value

    for col, value in zip(st.columns(len(options)), options):
        tile_button(col, value, ICONS[value], key=section_key(page, value),
                    selected=value == current, on_click=select, args=(value,))
    st.divider()
    return current


def remember_widget(container, kind, label, *, key, **kwargs):
    """Preserve an ordinary input when its widget is absent on a later rerun.

    Business values have independent keys. Call only for user-editable values,
    not buttons, uploaders, editor deltas, or one-time safety confirmations.
    """
    saved = f"rc6_value_{key}"
    widget = f"_rc6_value_{key}"
    state = st.session_state
    options = kwargs.get("options")
    if saved in state:
        value = deepcopy(state[saved])
        if options is not None:
            if kind == "multiselect":
                value = [item for item in value if item in options]
            else:
                value = valid_choice(value, options)
        if widget not in state or state[widget] != value:
            state[widget] = value
    def commit_value():
        state[saved] = deepcopy(state[widget])

    result = getattr(container, kind)(label, key=widget, on_change=commit_value, **kwargs)
    state[saved] = deepcopy(result)
    return result


def reset_remembered(key, value):
    """Reset the persistent and transient value before rendering the widget."""
    st.session_state[f"rc6_value_{key}"] = deepcopy(value)
    st.session_state.pop(f"_rc6_value_{key}", None)
