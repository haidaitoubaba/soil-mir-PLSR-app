from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
APP_FILES = [
    ROOT / "app" / "Home.py",
    ROOT / "app" / "pages" / "1_Data.py",
    ROOT / "app" / "pages" / "2_Configuration.py",
    ROOT / "app" / "pages" / "3_Run.py",
    ROOT / "app" / "pages" / "4_Results.py",
    ROOT / "app" / "pages" / "5_Predict.py",
    ROOT / "app" / "pages" / "6_Run_History.py",
]


@pytest.mark.parametrize("path", APP_FILES, ids=lambda path: path.stem)
def test_streamlit_page_renders_without_exception(path):
    app = AppTest.from_file(path, default_timeout=15)
    app.run()

    messages = [
        str(exception.value)
        for exception in app.exception
    ]
    assert not messages, (
        f"{path} raised Streamlit exceptions: {messages}"
    )


def test_cancelled_run_guidance_points_only_to_run_history():
    source = (ROOT / "app" / "pages" / "3_Run.py").read_text(encoding="utf-8")
    assert "Resume this run from Run History." in source
    assert "Use Resume on this page or in Run History." not in source



def test_run_history_delete_requires_explicit_confirmation():
    source = (
        ROOT / "app" / "pages" / "6_Run_History.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "🗑 Delete this run" in source
    assert "Delete permanently" in source
    assert "delete_saved_run(" in source
    assert "DELETABLE_RUN_STATUSES" in source
