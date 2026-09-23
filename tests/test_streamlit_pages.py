from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


APP_FILES = [
    Path("app/Home.py"),
    Path("app/pages/1_Data.py"),
    Path("app/pages/2_Configuration.py"),
    Path("app/pages/3_Run.py"),
    Path("app/pages/4_Results.py"),
    Path("app/pages/5_Predict.py"),
    Path("app/pages/6_Run_History.py"),
]


@pytest.mark.parametrize("path", APP_FILES, ids=lambda path: path.stem)
def test_streamlit_page_renders_without_exception(path):
    app = AppTest.from_file(str(path), default_timeout=15)
    app.run()

    messages = [
        str(exception.value)
        for exception in app.exception
    ]
    assert not messages, (
        f"{path} raised Streamlit exceptions: {messages}"
    )
