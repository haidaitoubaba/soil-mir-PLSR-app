"""Read desktop Cleanup v1 snapshots and write independently verified PCA copies."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from sklearn.decomposition import PCA
from threadpoolctl import threadpool_limits

from .calibration import (
    calibration_details,
    calibration_record,
    half_diagnostics,
    reviewed_half_decisions,
    selection_from,
)
from .offline import offline_html


AUTO_COMMENT = "Automatic cleanup; candidate spectra: "
MAX_FITS = 3
PCA_REASONS = {"", "redundancy", "spectral_quality", "range"}


def fingerprint(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def matrix_path(folder: Path, prop: dict) -> Path:
    name = prop.get("matrix", "")
    if not isinstance(name, str) or Path(name).name != name or not name.endswith(".npz"):
        raise ValueError("The session contains an invalid saved spectra filename.")
    path = folder / name
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or invalid saved spectra file: {name}")
    return path


def property_rows(prop: dict) -> dict:
    return {row["File Name"]: row for row in prop["frame"]}


def pca_rows(prop: dict) -> list:
    return (prop["pca"] or {}).get("rows", [])


def verified_snapshot(folder: Path) -> dict:
    path = folder / "session.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Select a saved Cleanup session folder that contains session.json.")
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("Select a Cleanup session in format version 1.")
    properties = state.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ValueError("The session has no saved properties.")

    # A read-only open does not run Desktop's interrupted-batch recovery against the source.
    checkpoint = state.pop("_auto_checkpoint", None)
    if checkpoint:
        state["properties"][checkpoint["property"]] = checkpoint["state"]
        state["history"] = state["history"][: checkpoint["history_length"]]
        state.pop("auto_cleanup", None)
        record_history(state, "Recovered interrupted automatic cleanup in web snapshot")

    for name, prop in properties.items():
        path = matrix_path(folder, prop)
        if fingerprint(path) != prop.get("matrix_sha256"):
            raise ValueError(f"{name}: saved spectra failed SHA-256 verification: {path.name}")
        records = property_rows(prop)
        if not records or len(records) != len(prop["frame"]):
            raise ValueError(f"{name}: reference rows are missing or duplicate a filename.")
        fitted = pca_rows(prop)
        if any(row["File Name"] not in records for row in fitted):
            raise ValueError(f"{name}: PCA scores do not match the saved reference records.")
    migrated = False
    for prop in properties.values():
        b = prop["diagnostics"].get("B")
        if b and b.get("selection_source") != "A":
            archive(prop, "Previous independently optimized B; decisions preserved")
            prop["diagnostics"] = {
                half: diagnostic for half, diagnostic in prop["diagnostics"].items() if half != "B"
            }
            prop["finished"] = {**prop["finished"], "B": False}
            migrated = True
    if migrated:
        record_history(
            state,
            "Updated B workflow: recalculate B using A settings; existing decisions preserved",
        )
    return state


def write_snapshot(folder: Path, state: dict) -> None:
    temp = folder / ".session.tmp"
    with temp.open("x", encoding="utf-8") as file:
        try:
            json.dump(state, file, indent=2, allow_nan=False)
            file.write("\n")
            file.close()
            temp.replace(folder / "session.json")
        finally:
            temp.unlink(missing_ok=True)


def record_history(state: dict, action: str) -> None:
    state.pop("last_export", None)
    event = {"time": datetime.now(timezone.utc).isoformat(), "action": action}
    state["history"] = [*state["history"], event]


def archive(prop: dict, label: str) -> None:
    snapshot = {key: prop[key] for key in ("pca", "diagnostics", "decisions", "halves")}
    prop["archive"] = [*prop["archive"], {"label": label, **snapshot}]


def compute_pca(matrix: np.ndarray, frame: list) -> tuple:
    """Use Desktop's full-SVD PCA rule and distances in all retained components."""
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2 or len(matrix) < 2 or not np.isfinite(matrix).all():
        raise ValueError("PCA requires at least two finite spectra.")
    if np.all(matrix == matrix[0]):
        raise ValueError("PCA has no nonzero components: spectra are constant.")
    model = PCA(n_components=min(15, len(matrix) - 1, matrix.shape[1]), svd_solver="full")
    with threadpool_limits(limits=1):
        scores = model.fit_transform(matrix)
    tolerance = np.finfo(float).eps * max(matrix.shape) * model.singular_values_[0]
    rank = int(np.sum(model.singular_values_ > tolerance))
    if not rank:
        raise ValueError("PCA has no nonzero components: spectra are constant.")
    scores = scores[:, :rank]
    rows = []
    for start in range(0, len(frame), 256):
        stop = min(start + 256, len(frame))
        distances = cdist(scores[start:stop], scores)
        indices = np.arange(stop - start)
        distances[indices, np.arange(start, stop)] = np.inf
        nearest = distances.argmin(axis=1)
        for offset, index in enumerate(nearest):
            row = frame[start + offset]
            neighbor = frame[index]
            rows.append(
                {
                    **row,
                    "scores": scores[start + offset].tolist(),
                    "Nearest File": neighbor["File Name"],
                    "Nearest Distance": float(distances[offset, index]),
                    "Same Sample Neighbour": row["Sample"] == neighbor["Sample"],
                }
            )
    return rows, model.explained_variance_ratio_[:rank].tolist()


def assign_halves(rows: list) -> dict:
    frame = pd.DataFrame(rows)
    ranked = pd.DataFrame(frame["scores"].tolist()).assign(Sample=frame["Sample"])
    means = ranked.groupby("Sample", sort=True).mean()
    count = len(means)
    if count < 4:
        raise ValueError("At least four retained samples are needed for the two halves.")
    distances = cdist(means.to_numpy(), means.to_numpy())
    first, second = map(int, np.unravel_index(np.argmax(distances), distances.shape))
    selected = [first, second if second != first else (first + 1) % count]
    while len(selected) < count // 2:
        nearest = distances[:, selected].min(axis=1)
        nearest[selected] = -np.inf
        selected.append(int(np.argmax(nearest)))
    half_a = set(means.index[selected])
    return {str(sample): "A" if sample in half_a else "B" for sample in means.index}


class DesktopReview:
    def __init__(self, path: str):
        source = Path(path.strip()).expanduser()
        if source.name == "session.json":
            source = source.parent
        self.source = source.resolve(strict=True)
        if not self.source.is_dir():
            raise ValueError("Enter a Cleanup session folder or its session.json path.")
        self.state = verified_snapshot(self.source)
        self.active = next(iter(self.state["properties"]))
        self.revision = 0
        self.undo = {}
        self.saved_path = None
        self.last_export = None
        self.export_revision = None
        self.changed = False
        self.suggested_path = self.destination_suggestion()

    def destination_suggestion(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.source.with_name(f"{self.source.name}_pca_web_{stamp}")

    def select(self, name: str) -> None:
        if name not in self.state["properties"]:
            raise ValueError("Select a property present in the desktop session.")
        self.active = name

    def change_decisions(self, prop: dict, action: dict) -> None:
        files = set(action.get("files", []))
        visible = {row["File Name"] for row in pca_rows(prop)}
        if not files or not files <= visible:
            raise ValueError("Select spectra in the current PCA fit.")
        unit, reason = action.get("unit"), action.get("reason", "")
        if unit not in {"spectrum", "sample"} or reason not in PCA_REASONS:
            raise ValueError("Choose a valid PCA exclusion unit and reason.")
        records = property_rows(prop)
        if unit == "sample":
            samples = {records[name]["Sample"] for name in files}
            files = {name for name, row in records.items() if row["Sample"] in samples}
        original = prop["decisions"]
        next_decisions = {name: item for name, item in original.items() if item["stage"] == "PCA"}
        first_pca = dict(next_decisions)
        for name in sorted(files):
            if action["kind"] == "restore":
                next_decisions.pop(name, None)
            elif name not in next_decisions:
                next_decisions[name] = {
                    "sample": str(records[name]["Sample"]),
                    "stage": "PCA",
                    "unit": unit,
                    "reason": reason,
                    "comment": str(action.get("comment", "")).strip(),
                }
        if next_decisions == first_pca:
            return
        if prop["pca_round"] >= MAX_FITS:
            raise ValueError("This property has reached the desktop limit of three PCA fits.")
        archive(prop, "Before PCA decision change (web)")
        prop.update(
            decisions=next_decisions,
            pca_dirty=True,
            pca_done=False,
            halves={},
            diagnostics={},
            finished={"A": False, "B": False},
        )

    def read_matrix(self, prop: dict) -> np.ndarray:
        path = matrix_path(self.source, prop)
        with path.open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != prop["matrix_sha256"]:
                raise ValueError(f"Saved spectra changed since opening: {path.name}")
            file.seek(0)
            with np.load(file, allow_pickle=False) as archive_file:
                matrix = archive_file["X"]
        frame = prop["frame"]
        if matrix.ndim != 2 or matrix.shape[0] != len(frame):
            raise ValueError(f"Spectra rows do not match reference rows: {path.name}")
        return matrix

    def refit(self, prop: dict) -> None:
        if not prop["pca_dirty"] or prop["pca_round"] >= MAX_FITS:
            raise ValueError("A PCA refit is unavailable for this property.")
        matrix = self.read_matrix(prop)
        frame = prop["frame"]
        excluded = {
            name for name, decision in prop["decisions"].items() if decision["stage"] == "PCA"
        }
        keep = [index for index, row in enumerate(frame) if row["File Name"] not in excluded]
        rows, variance = compute_pca(matrix[keep], [frame[index] for index in keep])
        if prop["pca"]:
            archive(prop, "Previous PCA basis")
        fit_round = prop["pca_round"] + 1
        prop.update(
            pca={"rows": rows, "variance": variance, "round": fit_round},
            pca_round=fit_round,
            pca_dirty=False,
        )

    def limit_usage(self, prop: dict, decisions: dict) -> tuple:
        percent = Decimal(str(self.state["percent"]))
        limit = self.state["limit"]
        if not percent.is_finite() or not 0 <= percent <= 100:
            raise ValueError("Percentage must be between 0 and 100.")
        if limit not in {"enable", "disable"}:
            raise ValueError("Invalid concentration limit setting.")
        samples = {
            decision["sample"]
            for decision in decisions.values()
            if decision["stage"] in {"A", "B"} or decision["reason"] == "concentration"
        }
        total = len({row["Sample"] for row in prop["frame"]})
        return limit == "enable", float(percent), len(samples), int(Decimal(total) * percent / 100)

    def validate_limit(self, prop: dict, decisions: dict, property_name=None) -> None:
        enabled, percent, used, cap = self.limit_usage(prop, decisions)
        if enabled and used > cap:
            raise ValueError(
                f"{property_name or self.active}: {used} concentration samples "
                "exceed the allowance "
                f"of {cap} ({percent:g}%)."
            )

    def calculate_half(self, prop: dict, half: str) -> bool:
        if not self.half_state(prop, half):
            raise ValueError(
                "Finish Half A review before calculating B."
                if half == "B"
                else "Finish PCA review first."
            )
        if half in prop["diagnostics"]:
            return False
        excluded = {name for name, item in prop["decisions"].items() if item["stage"] == "PCA"}
        a_exclusions = {name for name, item in prop["decisions"].items() if item["stage"] == "A"}
        a_selection = selection_from(prop["diagnostics"]["A"]) if half == "B" else None
        result = half_diagnostics(
            self.read_matrix(prop),
            prop["frame"],
            prop["config"],
            prop["halves"],
            excluded,
            half=half,
            a_selection=a_selection,
            a_exclusions=a_exclusions if half == "B" else (),
        )
        prop["diagnostics"] = {**prop["diagnostics"], half: result}
        return True

    def change_half_decisions(self, prop: dict, action: dict, half: str) -> None:
        diagnosis = prop["diagnostics"].get(half)
        if not diagnosis or not self.half_state(prop, half):
            raise ValueError(f"Calculate Half {half} before reviewing it.")
        decisions = reviewed_half_decisions(
            property_rows(prop), diagnosis["rows"], prop["decisions"], action, half
        )
        if decisions == prop["decisions"]:
            return
        self.validate_limit(prop, decisions)
        archive(prop, f"Before {half} decision change (web)")
        if half == "A":
            decisions = {
                name: record for name, record in decisions.items() if record["stage"] != "B"
            }
            prop["diagnostics"] = {
                key: value for key, value in prop["diagnostics"].items() if key != "B"
            }
            prop["finished"] = {"A": False, "B": False}
        else:
            prop["finished"] = {**prop["finished"], "B": False}
        prop["decisions"] = decisions

    def apply(self, action: dict) -> str:
        if action.get("revision") != self.revision or action.get("property") != self.active:
            raise ValueError("The displayed property or review changed. Try the operation again.")
        kind = action["kind"]
        stage = action.get("stage", "PCA")
        if stage not in {"PCA", "A", "B"}:
            raise ValueError("Unknown Cleanup review stage.")
        name = self.active
        previous = self.state["properties"][name]
        prop = dict(previous)
        if kind in {"exclude", "restore"}:
            if stage == "PCA":
                self.change_decisions(prop, action)
            else:
                self.change_half_decisions(prop, action, stage)
            label = "PCA" if stage == "PCA" else f"Half {stage}"
            if previous["decisions"] is prop["decisions"]:
                return f"No {label} decisions changed."
            self.undo[name] = (stage, previous)
            message = f"{name}: {label} decisions updated"
        elif kind == "undo":
            checkpoint = self.undo.get(name)
            if not checkpoint or checkpoint[0] != stage:
                raise ValueError("There is no decision to undo in this review stage.")
            _, prop = self.undo.pop(name)
            label = "PCA" if stage == "PCA" else f"Half {stage}"
            message = f"{name}: previous {label} decision restored"
        elif kind == "refit":
            self.refit(prop)
            message = f"{name}: PCA fit {prop['pca_round']} completed"
        elif kind == "finish":
            if prop["pca_dirty"]:
                raise ValueError("Refit PCA before finishing the review.")
            if not prop["pca_done"]:
                prop["halves"] = assign_halves(pca_rows(prop))
                prop["pca_done"] = True
            message = f"{name}: PCA review completed and sample groups assigned"
        elif kind in {"calculate-a", "calculate-b"}:
            half = kind[-1].upper()
            if not self.calculate_half(prop, half):
                return f"{name}: Half {half} diagnostics already available."
            message = f"{name}: Half {half} calculated"
        elif kind in {"finish-a", "finish-b"}:
            half = kind[-1].upper()
            if not self.half_state(prop, half) or half not in prop["diagnostics"]:
                raise ValueError(f"Calculate and review Half {half} first.")
            self.validate_limit(prop, prop["decisions"])
            prop["finished"] = {**prop["finished"], half: True}
            message = f"{name}: Half {half} review complete"
        else:
            raise ValueError("Unknown PCA action.")
        self.state["properties"][name] = prop
        record_history(self.state, f"{message} (web)")
        self.changed = True
        self.revision += 1
        return f"{message}. Save a copy to keep these changes."

    def save_as(self, path: str) -> Path:
        if not path.strip():
            raise ValueError("Enter a new folder for the saved copy.")
        requested = Path(path.strip()).expanduser()
        target = requested.parent.resolve(strict=True) / requested.name
        if target == self.source or target.is_relative_to(self.source):
            raise ValueError("Choose a new folder outside the original session.")
        try:
            target.mkdir()
        except FileExistsError as exc:
            raise ValueError("That destination already exists. Choose a new folder name.") from exc

        try:
            copied = set()
            for prop in self.state["properties"].values():
                source = matrix_path(self.source, prop)
                if source.name in copied:
                    continue
                target_matrix = target / source.name
                shutil.copyfile(source, target_matrix)
                if fingerprint(target_matrix) != prop["matrix_sha256"]:
                    raise ValueError(f"Saved spectra changed while copying: {source.name}")
                copied.add(source.name)
            snapshot = dict(self.state)
            record_history(snapshot, "Saved an independent Cleanup review copy from the web")
            if any(prop["pca"] for prop in self.state["properties"].values()):
                viewer = offline_html(self.all_property_data(), self.active)
                (target / "PCA_viewer.html").write_text(viewer, encoding="utf-8")
            write_snapshot(target, snapshot)
        except Exception:
            shutil.rmtree(target)
            raise
        self.changed = False
        self.saved_path = target
        self.suggested_path = self.destination_suggestion()
        if self.suggested_path == target:
            self.suggested_path = target.with_name(target.name + "_2")
        return target

    @staticmethod
    def half_state(prop: dict, half: str) -> str:
        if not prop["pca_done"] or prop["pca_dirty"]:
            return ""
        if half == "B" and (not prop["finished"]["A"] or not prop["diagnostics"].get("A")):
            return ""
        if half not in prop["diagnostics"]:
            return f"Calculate {half}"
        return f"{half} complete" if prop["finished"][half] else f"Review {half}"

    def property_data(self, name: str, *, include_calibration=True) -> dict:
        prop = self.state["properties"][name]
        fitted = {row["File Name"]: row for row in pca_rows(prop)}
        calibration_rows = (
            {half: prop["diagnostics"].get(half, {}).get("rows", []) for half in ("A", "B")}
            if include_calibration
            else {}
        )
        diagnostics = {
            row["File Name"]: row for half_rows in calibration_rows.values() for row in half_rows
        }
        rows = []
        for original in prop["frame"]:
            file = original["File Name"]
            sample = str(original["Sample"])
            decision = prop["decisions"].get(file, {})
            score = fitted.get(file, {})
            record = {
                "sample": sample,
                "file": file,
                "group": str(original["Group"]),
                "reference": float(original["Reference Value"]),
                "status": "Excluded" if decision else "Retained",
                "decision_stage": decision.get("stage", ""),
                "reason": decision.get("reason", ""),
                "comment": decision.get("comment", ""),
                "automatic": str(decision.get("comment", "")).startswith(AUTO_COMMENT),
                "half": prop["halves"].get(sample, ""),
            }
            if score:
                record.update(
                    scores=score["scores"],
                    neighbor=score["Nearest File"],
                    distance=round(score["Nearest Distance"], 4),
                    same_sample=score["Same Sample Neighbour"],
                )
            diagnostic = diagnostics.get(file)
            if diagnostic:
                record.update(calibration_record(diagnostic))
            rows.append(record)
        halves = list(prop["halves"].values())
        calibrations = {}
        if any(calibration_rows.values()):
            enabled, percent, used, cap = self.limit_usage(prop, prop["decisions"])
            limit = {"enabled": enabled, "percent": percent, "used": used, "cap": cap}
            for half, half_rows in calibration_rows.items():
                if half_rows:
                    calibrations[half] = calibration_details(
                        half_rows[0],
                        prop["config"],
                        prop["finished"][half],
                        limit,
                        has_b=bool(calibration_rows.get("B")),
                    )
        return {
            "rows": rows,
            "variance": [100 * value for value in (prop["pca"] or {}).get("variance", [])],
            "round": prop["pca_round"],
            "dirty": prop["pca_dirty"],
            "undo": name in self.undo,
            "undoStage": self.undo[name][0] if name in self.undo else "",
            "halfAState": self.half_state(prop, "A"),
            "halfBState": self.half_state(prop, "B"),
            "calibrations": calibrations,
            "split": [halves.count(half) for half in ("A", "B")],
            "hasDownstream": bool(prop["pca_done"] or prop["halves"] or prop["diagnostics"]),
        }

    def all_property_data(self) -> dict:
        return {
            name: self.property_data(name, include_calibration=False)
            for name in self.state["properties"]
        }

    def workbench_data(self, notice: dict | None) -> dict:
        name = self.active
        return {
            "mode": "desktop",
            "activeProperty": name,
            "propertyNames": list(self.state["properties"]),
            "propertyStates": {
                key: self.half_state(prop, "B") or self.half_state(prop, "A")
                for key, prop in self.state["properties"].items()
            },
            "revision": self.revision,
            "notice": notice,
            "dirtyDraft": self.changed,
            "source": str(self.source),
            "sessionLabel": self.source.name,
            "savedCopy": str(self.saved_path) if self.saved_path else "",
            "suggestedCopy": str(self.suggested_path),
            "properties": {name: self.property_data(name)},
        }
