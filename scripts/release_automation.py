"""Protected GitLab CI release orchestration for Soil MIR PLSR (stdlib only)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "86646772"
REPOSITORY = "haidaitoubaba/soil-mir-PLSR-app"
GL_BASE = f"https://gitlab.com/api/v4/projects/{PROJECT_ID}"
GH_BASE = f"https://api.github.com/repos/{REPOSITORY}"
VERSION_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
APPROVAL_RE = re.compile(r"soil-mir-approved (v\d+\.\d+\.\d+-rc[1-9]\d*) pipeline (\d+)")
PACKAGING_JOBS = {"mac_rc_bundle", "windows_rc_bundle"}
QUALITY_JOBS = {"ci_config_check", "quality"}


class ReleaseError(RuntimeError):
    """A safe diagnostic; never include credentials or raw HTTP bodies."""


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Api:
    def __init__(self, base, headers):
        self.base = base
        self.headers = headers
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, payload=None, *, missing=False, binary=None):
        url = self.base + path
        headers = dict(self.headers)
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if binary is not None:
            data = binary
            headers["Content-Type"] = "application/octet-stream"
        try:
            with self.opener.open(
                Request(url, data=data, headers=headers, method=method), timeout=30
            ) as response:
                body = response.read()
                return json.loads(body) if body else None
        except HTTPError as exc:
            if missing and exc.code == 404:
                return None
            raise ReleaseError(f"API {method} failed (HTTP {exc.code}).") from None
        except (URLError, TimeoutError):
            raise ReleaseError(f"API {method} network error; retry the job.") from None

    def all(self, path, **query):
        for page in range(1, 101):
            params = urlencode({**query, "page": page, "per_page": 100})
            items = self.request("GET", f"{path}?{params}")
            require(isinstance(items, list), "Expected paginated API list.")
            yield from items
            if len(items) < 100:
                return
        raise ReleaseError("API pagination limit exceeded.")


def secret(name):
    value = os.environ.get(name)
    require(bool(value), f"Missing protected CI/CD variable {name}.")
    return value


def context():
    require(os.environ.get("CI_PROJECT_ID") == PROJECT_ID, "Wrong GitLab project.")
    require(os.environ.get("CI_COMMIT_REF_PROTECTED") == "true", "Unprotected ref.")
    sha = os.environ.get("CI_COMMIT_SHA", "")
    pipeline = os.environ.get("CI_PIPELINE_ID", "")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", sha)), "Invalid commit SHA.")
    require(pipeline.isdecimal(), "Invalid pipeline ID.")
    return sha, int(pipeline)


def tag_info(gl, tag):
    return gl.request("GET", f"/repository/tags/{quote(tag, safe='')}", missing=True)


def tag_sha(info):
    return (info or {}).get("commit", {}).get("id")


def pipeline_jobs(gl, pipeline, ref, sha, required):
    data = gl.request("GET", f"/pipelines/{pipeline}")
    require(data["sha"] == sha and data["ref"] == ref, "Pipeline/ref mismatch.")
    jobs = list(gl.all(f"/pipelines/{pipeline}/jobs"))
    passed = {job["name"] for job in jobs if job["status"] == "success"}
    require(required <= passed, "Required jobs have not all succeeded.")


def require_current_main(gl, sha):
    main = gl.request("GET", "/repository/branches/main")
    require(main["commit"]["id"] == sha, "Main changed; create a new candidate.")


def ensure_tag(gl, tag, sha, message):
    existing = tag_info(gl, tag)
    if existing:
        require(tag_sha(existing) == sha, f"Tag {tag} already points elsewhere.")
        require(existing.get("message") == message, f"Tag {tag} has different provenance.")
    else:
        created = gl.request(
            "POST", "/repository/tags", {"tag_name": tag, "ref": sha, "message": message}
        )
        require(tag_sha(created) == sha, "Created tag SHA mismatch.")
    # Tag creation normally starts a pipeline. Avoid launching a duplicate.
    for _ in range(6):
        pipelines = list(gl.all("/pipelines", ref=tag, sha=sha))
        if pipelines:
            newest = max(pipelines, key=lambda item: item["id"])
            print(f"Tag {tag}; pipeline {newest['id']} ({newest['status']}).")
            require(
                newest["status"] not in {"failed", "canceled"},
                "Existing tag pipeline failed; retry its failed jobs.",
            )
            return
        time.sleep(5)
    created = gl.request("POST", "/pipeline", {"ref": tag})
    require(created["sha"] == sha, "Triggered pipeline SHA mismatch.")
    print(f"Tag {tag}; pipeline {created['id']}.")


def notes_for(version):
    path = ROOT / f"RELEASE_NOTES_{version}.md"
    require(path.is_file(), f"Missing release notes: {path.name}")
    notes = path.read_text(encoding="utf-8").strip()
    require(bool(notes), "Release notes are empty.")
    return notes


def candidate(gl, version, sha, pipeline):
    require_current_main(gl, sha)
    pipeline_jobs(gl, pipeline, "main", sha, QUALITY_JOBS)
    if tag_info(gl, version):
        print(f"{version} already has a final tag; bump the project version first.")
        return
    notes_for(version)
    pattern = re.compile(re.escape(version) + r"-rc([1-9]\d*)")
    candidates = []
    for item in gl.all("/repository/tags", search=f"^{version}-rc"):
        match = pattern.fullmatch(item["name"])
        if match:
            candidates.append((int(match[1]), item))
    message = f"soil-mir-candidate {sha}"
    for _, item in sorted(candidates, key=lambda pair: pair[0], reverse=True):
        if tag_sha(item) == sha:
            require(item.get("message") == message, "Existing candidate has unknown provenance.")
            ensure_tag(gl, item["name"], sha, message)
            return
    number = max((n for n, _ in candidates), default=0) + 1
    ensure_tag(gl, f"{version}-rc{number}", sha, message)


def promote(gl, version, sha, pipeline, rc):
    require(
        bool(re.fullmatch(re.escape(version) + r"-rc[1-9]\d*", rc)),
        "Not a candidate for the current project version.",
    )
    require_current_main(gl, sha)
    info = tag_info(gl, rc)
    require(tag_sha(info) == sha, "Candidate tag SHA mismatch.")
    require(info.get("message") == f"soil-mir-candidate {sha}", "Unmanaged candidate.")
    pipeline_jobs(gl, pipeline, rc, sha, PACKAGING_JOBS)
    notes_for(version)
    ensure_tag(gl, version, sha, f"soil-mir-approved {rc} pipeline {pipeline}")


def verify_approval(gl, version, sha):
    info = tag_info(gl, version)
    require(tag_sha(info) == sha, "Official tag SHA mismatch.")
    match = APPROVAL_RE.fullmatch((info or {}).get("message") or "")
    require(match is not None, "Final tag was not created by candidate promotion.")
    rc, pipeline = match.groups()
    require(
        bool(re.fullmatch(re.escape(version) + r"-rc[1-9]\d*", rc)),
        "Approval refers to a different version.",
    )
    candidate_info = tag_info(gl, rc)
    require(tag_sha(candidate_info) == sha, "Approved candidate SHA mismatch.")
    require(
        candidate_info.get("message") == f"soil-mir-candidate {sha}",
        "Unmanaged approved candidate.",
    )
    pipeline_jobs(gl, int(pipeline), rc, sha, PACKAGING_JOBS)


def wait_for_mirror(gh, version, sha):
    for _ in range(18):
        commit = gh.request("GET", f"/commits/{quote(version, safe='')}", missing=True)
        if commit:
            require(commit["sha"] == sha, "GitHub tag SHA mismatch; refusing release.")
            return
        time.sleep(10)
    raise ReleaseError("GitHub tag has not mirrored yet; retry the publish job.")


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def release_files(version, dist):
    filenames = [
        f"soil-mir-app-{version}-mac.tar.gz",
        f"soil-mir-app-{version}-windows.zip",
    ]
    files = {}
    for name in filenames:
        path = dist / name
        require(path.is_file() and path.stat().st_size > 0, f"Missing package: {name}")
        files[name] = path.read_bytes()
    checksums = "".join(f"{digest(data)[7:]}  {name}\n" for name, data in files.items())
    files["SHA256SUMS.txt"] = checksums.encode()
    return files


def asset_matches(asset, data):
    return (
        asset.get("state") == "uploaded"
        and asset.get("size") == len(data)
        and asset.get("digest") == digest(data)
    )


def verify_assets(gh, release_id, files):
    assets = list(gh.all(f"/releases/{release_id}/assets"))
    require(len(assets) == len(files), "Unexpected asset count.")
    require({asset["name"] for asset in assets} == set(files), "Asset names mismatch.")
    for asset in assets:
        require(
            asset_matches(asset, files[asset["name"]]),
            f"Asset integrity check failed: {asset['name']}",
        )
    return assets


def version_key(tag):
    match = VERSION_RE.fullmatch(tag)
    return tuple(map(int, match.groups())) if match else None


def publish_github(gh, uploads, version, sha, files, notes):
    wait_for_mirror(gh, version, sha)
    marker = f"<!-- soil-mir-release project={PROJECT_ID} sha={sha} -->"
    releases = list(gh.all("/releases"))
    matches = [item for item in releases if item["tag_name"] == version]
    require(len(matches) <= 1, "Multiple releases for this tag.")
    existing = matches[0] if matches else None
    if existing:
        require(marker in (existing.get("body") or ""), "Existing unmanaged release; untouched.")
        if not existing["draft"]:
            require(not existing["prerelease"], "Existing release is a prerelease.")
            verify_assets(gh, existing["id"], files)
            print(f"Release {version} already published and verified; unchanged.")
            return existing
    for item in releases:
        key = version_key(item["tag_name"])
        if key and not item["draft"] and not item["prerelease"]:
            require(key <= version_key(version), "A newer official release already exists.")
    if not existing:
        existing = gh.request(
            "POST",
            "/releases",
            {
                "tag_name": version,
                "name": f"Soil MIR PLSR App {version}",
                "body": f"{notes}\n\n{marker}",
                "draft": True,
                "prerelease": False,
                "make_latest": "false",
            },
        )
    require(existing["draft"] and not existing["prerelease"], "Expected managed draft.")
    release_id = existing["id"]
    assets = list(gh.all(f"/releases/{release_id}/assets"))
    require(
        len({item["name"] for item in assets}) == len(assets)
        and all(item["name"] in files for item in assets),
        "Unexpected draft assets; no changes made.",
    )
    by_name = {item["name"]: item for item in assets}
    for name, data in files.items():
        asset = by_name.get(name)
        if asset and asset_matches(asset, data):
            continue
        if asset:
            # Only repair our own unpublished draft, never a public release.
            gh.request("DELETE", f"/releases/assets/{asset['id']}")
        query = urlencode({"name": name})
        uploaded = uploads.request(
            "POST", f"/releases/{release_id}/assets?{query}", binary=data
        )
        require(asset_matches(uploaded, data), f"Upload digest mismatch: {name}")
    verify_assets(gh, release_id, files)
    wait_for_mirror(gh, version, sha)
    published = gh.request(
        "PATCH", f"/releases/{release_id}", {"draft": False, "make_latest": "true"}
    )
    require(not published["draft"] and not published["prerelease"], "Publish failed.")
    verify_assets(gh, release_id, files)
    print(f"Published and verified GitHub release {version}.")
    return published


def record_gitlab(gl, version, notes, github_release):
    existing = gl.request("GET", f"/releases/{quote(version, safe='')}", missing=True)
    if existing:
        print(f"GitLab release {version} already exists; unchanged.")
        return
    url = f"https://github.com/{REPOSITORY}/releases/tag/{version}"
    gl.request(
        "POST",
        "/releases",
        {
            "tag_name": version,
            "name": f"Soil MIR PLSR App {version}",
            "description": f"{notes}\n\n[Public downloads]({url})",
            "assets": {"links": [
                {"name": item["name"], "url": item["browser_download_url"]}
                for item in github_release.get("assets", [])
            ]},
        },
    )
    print(f"Recorded GitLab release {version}.")


def main():
    from release_common import validate_release_inputs

    require(len(sys.argv) == 2, "Expected candidate, promote or publish.")
    action = sys.argv[1]
    require(action in {"candidate", "promote", "publish"}, "Invalid release action.")
    sha, pipeline = context()
    version = f"v{validate_release_inputs()}"
    require(version_key(version) is not None, "Expected a stable semantic version.")
    gl = Api(GL_BASE, {"PRIVATE-TOKEN": secret("GITLAB_RELEASE_TOKEN")})
    ref = os.environ.get("CI_COMMIT_TAG", "")
    if action == "candidate":
        require(os.environ.get("CI_COMMIT_BRANCH") == "main", "Expected main branch.")
        candidate(gl, version, sha, pipeline)
    elif action == "promote":
        promote(gl, version, sha, pipeline, ref)
    else:
        require(ref == version, "Official tag does not match project version.")
        verify_approval(gl, version, sha)
        pipeline_jobs(gl, pipeline, ref, sha, PACKAGING_JOBS)
        notes = notes_for(version)
        files = release_files(version, ROOT / "dist")
        headers = {
            "Authorization": f"Bearer {secret('GITHUB_RELEASE_TOKEN')}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        github_release = publish_github(
            Api(GH_BASE, headers),
            Api(f"https://uploads.github.com/repos/{REPOSITORY}", headers),
            version, sha, files, notes,
        )
        record_gitlab(gl, version, notes, github_release)


if __name__ == "__main__":
    try:
        main()
    except ReleaseError as exc:
        sys.exit(str(exc))
