"""Offline regression tests for the release gate; no live API writes."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "release_automation", ROOT / "scripts" / "release_automation.py"
)
assert spec and spec.loader
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
SHA = "a" * 40
VERSION = "v9.8.7"
RC = VERSION + "-rc1"


def test_release_files_require_both_and_checksum(tmp_path):
    mac = f"soil-mir-app-{VERSION}-mac.tar.gz"
    win = f"soil-mir-app-{VERSION}-windows.zip"
    (tmp_path / mac).write_bytes(b"mac")
    with pytest.raises(release.ReleaseError, match="Missing package"):
        release.release_files(VERSION, tmp_path)
    (tmp_path / win).write_bytes(b"win")
    files = release.release_files(VERSION, tmp_path)
    assert set(files) == {mac, win, "SHA256SUMS.txt"}
    for name in (mac, win):
        assert f"{release.digest(files[name])[7:]}  {name}\n".encode() in files[
            "SHA256SUMS.txt"
        ]


def test_failed_package_blocks_approval():
    gl = Mock()
    gl.request.return_value = {"ref": RC, "sha": SHA}
    gl.all.return_value = iter([
        {"name": "mac_rc_bundle", "status": "success"},
        {"name": "windows_rc_bundle", "status": "failed"},
    ])
    with pytest.raises(release.ReleaseError, match="Required jobs"):
        release.pipeline_jobs(gl, 1, RC, SHA, release.PACKAGING_JOBS)


def test_unapproved_final_tag_blocks_publication():
    gl = Mock()
    gl.request.return_value = {"commit": {"id": SHA}, "message": "manually created"}
    with pytest.raises(release.ReleaseError, match="not created by candidate promotion"):
        release.verify_approval(gl, VERSION, SHA)


def test_mirror_sha_mismatch_fails_closed():
    gh = Mock()
    gh.request.return_value = {"sha": "b" * 40}
    with pytest.raises(release.ReleaseError, match="SHA mismatch"):
        release.wait_for_mirror(gh, VERSION, SHA)


def test_existing_final_tag_is_not_overwritten():
    gl = Mock()
    gl.request.side_effect = [
        {"commit": {"id": SHA}},
        {"sha": SHA, "ref": "main"},
        {"commit": {"id": SHA}},
    ]
    gl.all.return_value = iter(
        {"name": name, "status": "success"} for name in release.QUALITY_JOBS
    )
    release.candidate(gl, VERSION, SHA, 1)
    assert all(call.args[0] == "GET" for call in gl.request.call_args_list)


def test_existing_tag_wrong_sha_is_not_moved():
    gl = Mock()
    gl.request.return_value = {"commit": {"id": "b" * 40}}
    with pytest.raises(release.ReleaseError, match="already points elsewhere"):
        release.ensure_tag(gl, RC, SHA, "candidate")
    assert gl.request.call_count == 1


def test_asset_matches_requires_uploaded_state_size_and_digest():
    data = b"example"
    good = {"size": len(data), "digest": release.digest(data), "state": "uploaded"}
    assert release.asset_matches(good, data)
    for bad in ({"digest": "wrong"}, {"state": "starter"}, {"size": 0}, {"digest": None}):
        assert not release.asset_matches({**good, **bad}, data)


def test_existing_unmanaged_public_release_is_untouched():
    gh = Mock()
    gh.request.return_value = {"sha": SHA}
    gh.all.return_value = iter([{"tag_name": VERSION, "body": "", "draft": False}])
    uploads = Mock()
    with pytest.raises(release.ReleaseError, match="unmanaged release"):
        release.publish_github(gh, uploads, VERSION, SHA, {"file": b"x"}, "notes")
    uploads.request.assert_not_called()
    assert all(call.args[0] == "GET" for call in gh.request.call_args_list)


def test_newer_release_blocks_old_publish():
    gh = Mock()
    gh.request.return_value = {"sha": SHA}
    gh.all.return_value = iter([
        {"tag_name": "v10.0.0", "draft": False, "prerelease": False}
    ])
    with pytest.raises(release.ReleaseError, match="newer official release"):
        release.publish_github(gh, Mock(), VERSION, SHA, {"file": b"x"}, "notes")


def test_draft_upload_verify_then_publish():
    gh = Mock()
    uploads = Mock()
    data = b"x"
    asset = {"id": 3, "name": "file", "size": 1, "state": "uploaded",
             "digest": release.digest(data)}
    gh.request.side_effect = [
        {"sha": SHA}, {"id": 2, "draft": True, "prerelease": False},
        {"sha": SHA}, {"id": 2, "draft": False, "prerelease": False},
    ]
    gh.all.side_effect = [iter([]), iter([]), iter([asset]), iter([asset])]
    uploads.request.return_value = asset
    result = release.publish_github(gh, uploads, VERSION, SHA, {"file": data}, "notes")
    assert result["draft"] is False
    assert gh.request.call_args_list[1].args[2]["draft"] is True
    assert gh.request.call_args_list[-1].args[2]["draft"] is False
    uploads.request.assert_called_once_with("POST", "/releases/2/assets?name=file", binary=data)


def test_failed_upload_never_publishes():
    gh = Mock()
    uploads = Mock()
    gh.request.side_effect = [
        {"sha": SHA}, {"id": 2, "draft": True, "prerelease": False},
    ]
    gh.all.side_effect = [iter([]), iter([])]
    uploads.request.return_value = {"state": "starter"}
    with pytest.raises(release.ReleaseError, match="digest mismatch"):
        release.publish_github(gh, uploads, VERSION, SHA, {"file": b"x"}, "notes")
    assert all(call.args[0] != "PATCH" for call in gh.request.call_args_list)


def test_managed_draft_retry_reuses_verified_asset():
    gh = Mock()
    uploads = Mock()
    asset = {"id": 3, "name": "file", "size": 1, "state": "uploaded",
             "digest": release.digest(b"x")}
    draft = {"id": 2, "tag_name": VERSION, "draft": True, "prerelease": False,
             "body": f"<!-- soil-mir-release project={release.PROJECT_ID} sha={SHA} -->"}
    gh.request.side_effect = [
        {"sha": SHA}, {"sha": SHA}, {"id": 2, "draft": False, "prerelease": False},
    ]
    gh.all.side_effect = [iter([draft]), iter([asset]), iter([asset]), iter([asset])]
    release.publish_github(gh, uploads, VERSION, SHA, {"file": b"x"}, "notes")
    uploads.request.assert_not_called()
