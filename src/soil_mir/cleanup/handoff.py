"""Transfer a verified, current Cleanup export to the Modeling Data page."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from soil_mir.io.opus import list_opus_files

if TYPE_CHECKING:
    from .desktop_session import DesktopReview


@dataclass(frozen=True)
class PropertyRetention:
    name: str
    samples: int
    spectra: int


@dataclass(frozen=True)
class CleanupHandoff:
    spectra: Path
    workbook: Path
    workbook_hash: str
    properties: tuple[PropertyRetention, ...]

    def verify_workbook(self) -> None:
        if file_sha256(self.workbook) != self.workbook_hash:
            raise ValueError(
                "The cleaned workbook changed after export. Export it again in Cleanup."
            )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_handoff(review: DesktopReview, spectra: str) -> CleanupHandoff:
    export = review.last_export
    if export is None or review.export_revision != review.revision:
        raise ValueError("Export the current Cleanup review first.")
    if not spectra.strip():
        raise ValueError("Enter the original OPUS spectra directory.")
    folder = Path(spectra).expanduser().resolve(strict=True)
    files = {path.name: path for path in list_opus_files(folder)}
    hashes = review.state.get("spectra_sha256", {})
    required = set()
    properties = []
    for name, prop in review.state["properties"].items():
        kept = [row for row in prop["frame"] if row["File Name"] not in prop["decisions"]]
        required.update(row["File Name"] for row in kept)
        properties.append(PropertyRetention(name, len({row["Sample"] for row in kept}), len(kept)))
    if missing := sorted(required - files.keys()):
        raise ValueError(f"{len(missing)} retained OPUS file(s) missing: {', '.join(missing[:5])}.")
    for name in sorted(required & hashes.keys()):
        if file_sha256(files[name]) != hashes[name]:
            raise ValueError(f"OPUS file changed since Cleanup session creation: {name}.")

    workbook = export / "reference_cleaned.xlsx"
    provenance = json.loads(workbook.with_suffix(".cleanup.json").read_text(encoding="utf-8"))
    workbook_hash = provenance.get("cleaned_sha256") if isinstance(provenance, dict) else None
    if not isinstance(workbook_hash, str):
        raise ValueError("The Cleanup export is missing its workbook fingerprint.")
    transfer = CleanupHandoff(folder, workbook, workbook_hash, tuple(properties))
    transfer.verify_workbook()
    return transfer
