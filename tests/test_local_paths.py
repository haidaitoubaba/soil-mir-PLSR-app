import base64
from pathlib import Path

from types import SimpleNamespace

import pytest

from soil_mir.services import local_paths
from soil_mir.services.local_paths import (
    choose_local_path,
    detect_local_data_layout,
    load_path_preferences,
    open_local_folder,
    save_path_preferences,
)


def _make_layout(data_dir: Path):
    spectra = data_dir / "spectra" / "Complete"
    reference = data_dir / "reference"
    spectra.mkdir(parents=True)
    reference.mkdir(parents=True)
    (
        reference
        / "reference_value_ZL_trt.xlsx"
    ).write_bytes(b"placeholder")


def test_environment_data_dir_takes_precedence(tmp_path):
    configured = tmp_path / "configured"
    project = tmp_path / "project"
    _make_layout(configured)
    _make_layout(project / "data")

    layout = detect_local_data_layout(
        home=tmp_path / "home",
        cwd=project,
        environ={
            "SOIL_MIR_DATA_DIR": str(configured)
        },
    )

    assert layout is not None
    assert layout.data_dir == configured
    assert layout.source == "SOIL_MIR_DATA_DIR"


def test_detects_legacy_downloads_layout(tmp_path):
    home = tmp_path / "home"
    data_dir = (
        home
        / "Downloads"
        / "Python Code for Zheya"
        / "Python code for MIR"
        / "data"
    )
    _make_layout(data_dir)

    layout = detect_local_data_layout(
        home=home,
        cwd=tmp_path / "other",
        environ={},
    )

    assert layout is not None
    assert layout.data_dir == data_dir
    assert (
        layout.reference_excel.name
        == "reference_value_ZL_trt.xlsx"
    )
    assert (
        layout.spectra_dir
        == data_dir / "spectra" / "Complete"
    )


def test_returns_none_when_layout_is_missing(tmp_path):
    layout = detect_local_data_layout(
        home=tmp_path / "home",
        cwd=tmp_path / "project",
        environ={},
    )
    assert layout is None


def test_path_preferences_round_trip(tmp_path):
    saved = save_path_preferences(
        tmp_path / "spectra",
        tmp_path / "reference.xlsx",
        tmp_path / "results",
        home=tmp_path / "home",
    )

    assert saved.is_file()
    assert load_path_preferences(
        home=tmp_path / "home"
    ) == {
        "spectra_dir": str(tmp_path / "spectra"),
        "reference_excel": str(
            tmp_path / "reference.xlsx"
        ),
        "output_dir": str(tmp_path / "results"),
    }


def test_invalid_path_preferences_are_ignored(tmp_path):
    path = (
        tmp_path
        / "home"
        / ".soil_mir_app"
        / "paths.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    assert load_path_preferences(
        home=tmp_path / "home"
    ) == {}


def test_macos_native_picker_returns_selected_path(
    monkeypatch,
):
    def fake_run(
        args,
        capture_output,
        text,
        check,
    ):
        assert args[0] == "osascript"
        assert "choose folder" in args[-1]
        assert capture_output
        assert text
        assert check is False
        return SimpleNamespace(
            returncode=0,
            stdout="/tmp/soil spectra/\n",
            stderr="",
        )

    monkeypatch.setattr(
        local_paths.subprocess,
        "run",
        fake_run,
    )

    selected = choose_local_path(
        "directory",
        prompt="Choose spectra",
        platform_name="darwin",
    )

    assert selected == Path("/tmp/soil spectra")


def test_macos_native_picker_cancel_returns_none(
    monkeypatch,
):
    monkeypatch.setattr(
        local_paths.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="execution error: User canceled. (-128)",
        ),
    )

    selected = choose_local_path(
        "file",
        prompt="Choose workbook",
        platform_name="darwin",
    )

    assert selected is None


def test_windows_native_picker_returns_unicode_path(monkeypatch):
    selected_text = r"C:\\Soil 数据\\Spectra"
    encoded = base64.b64encode(selected_text.encode("utf-8")).decode("ascii")

    def fake_run(args, capture_output, text, check, env):
        assert args[0] == "powershell.exe"
        assert "-STA" in args
        assert "FolderBrowserDialog" in args[-1]
        assert capture_output
        assert text
        assert check is False
        assert env["SOIL_MIR_PICKER_PROMPT"] == "Choose spectra"
        return SimpleNamespace(returncode=0, stdout=encoded, stderr="")

    monkeypatch.setattr(local_paths.subprocess, "run", fake_run)

    selected = choose_local_path(
        "directory",
        prompt="Choose spectra",
        platform_name="win32",
    )

    assert selected == Path(selected_text)


def test_windows_native_picker_cancel_returns_none(monkeypatch):
    monkeypatch.setattr(
        local_paths.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=2,
            stdout="",
            stderr="",
        ),
    )

    selected = choose_local_path(
        "file",
        prompt="Choose workbook",
        platform_name="win32",
    )

    assert selected is None


def test_native_picker_rejects_unsupported_desktop_platform():
    with pytest.raises(
        RuntimeError,
        match="macOS and Windows",
    ):
        choose_local_path(
            "directory",
            prompt="Choose folder",
            platform_name="linux",
        )



def test_open_local_folder_uses_macos_finder(
    tmp_path,
    monkeypatch,
):
    opened = []

    def fake_run(
        args,
        capture_output,
        text,
        check,
    ):
        opened.append(args)
        assert capture_output
        assert text
        assert check is False
        return SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        local_paths.subprocess,
        "run",
        fake_run,
    )

    result = open_local_folder(
        tmp_path,
        platform_name="darwin",
    )

    assert result == tmp_path
    assert opened == [
        ["open", str(tmp_path)]
    ]


def test_open_local_folder_rejects_missing_directory(
    tmp_path,
):
    with pytest.raises(
        FileNotFoundError,
        match="Results folder not found",
    ):
        open_local_folder(
            tmp_path / "missing",
            platform_name="darwin",
        )


def test_open_local_folder_uses_windows_explorer(
    tmp_path,
    monkeypatch,
):
    opened = []
    monkeypatch.setattr(
        local_paths.os,
        "startfile",
        lambda value: opened.append(value),
        raising=False,
    )

    result = open_local_folder(
        tmp_path,
        platform_name="win32",
    )

    assert result == tmp_path
    assert opened == [str(tmp_path)]


def test_open_local_folder_reports_unsupported_platform(
    tmp_path,
):
    with pytest.raises(
        RuntimeError,
        match="macOS and Windows",
    ):
        open_local_folder(
            tmp_path,
            platform_name="linux",
        )
