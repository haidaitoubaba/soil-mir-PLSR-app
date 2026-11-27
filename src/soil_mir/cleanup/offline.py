"""Build a self-contained, read-only view of the current PCA results."""

import json
from pathlib import Path


UI = Path(__file__).with_name("workbench")


def offline_html(properties, current):
    fields = (
        "sample",
        "file",
        "group",
        "reference",
        "scores",
        "status",
        "decision_stage",
        "neighbor",
        "distance",
    )
    fits = {
        name: {
            "round": prop["round"],
            "dirty": prop["dirty"],
            "variance": prop["variance"],
            "rows": [
                {key: row[key] for key in fields if key in row}
                for row in prop["rows"]
                if row.get("scores")
            ],
        }
        for name, prop in properties.items()
        if prop["variance"]
    }
    if not fits:
        raise ValueError("There are no PCA scores to open. Fit a property first.")
    data = json.dumps(
        {"properties": fits, "current": current if current in fits else next(iter(fits))},
        allow_nan=False,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    document = (UI / "offline.html").read_text(encoding="utf-8")
    markup, marker, end = document.partition("<!-- INLINE_PCA -->")
    if not marker:
        raise ValueError("Missing offline PCA viewer template marker.")
    scripts = "\n".join(
        (UI / name).read_text(encoding="utf-8") for name in ("chart.mjs", "offline.mjs")
    )
    payload = '<script type="application/json" id="pca-data">' + data + "</script>"
    initialize = 'const SNAPSHOT = JSON.parse(document.getElementById("pca-data").textContent);'
    return markup + payload + "<script>" + initialize + "\n" + scripts + "</script>" + end
