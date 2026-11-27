"""Headless PCA and calibration reports for a completed export."""

import re
from threading import Lock

import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure


FIGURE_LOCK = Lock()


def pca_figures(properties, folder):
    with PdfPages(folder / "PCA_report.pdf") as pdf:
        for index, (name, prop) in enumerate(properties.items()):
            rows = [row for row in prop["rows"] if row.get("scores")]
            if not rows:
                continue
            scores = np.array([row["scores"] for row in rows])
            excluded = np.array([row["status"] == "Excluded" for row in rows])
            y = min(1, scores.shape[1] - 1)
            variances = prop["variance"]
            fig = Figure(figsize=(16, 4.5), layout="constrained")
            scatter, variance, histogram = fig.subplots(1, 3)
            for mask, label, color in [
                (~excluded, "Retained", "#237a95"),
                (excluded, "Confirmed excluded", "#bb354d"),
            ]:
                scatter.scatter(scores[mask, 0], scores[mask, y], s=12, label=label, color=color)
            scatter.set(
                xlabel=f"PC1 ({variances[0]:.1f}%)", ylabel=f"PC{y + 1} ({variances[y]:.1f}%)"
            )
            scatter.legend(fontsize=8)
            variance.bar(np.arange(1, len(variances) + 1), variances, color="#237a95")
            variance.set(xlabel="Principal component", ylabel="Explained variance (%)")
            samples = {row["sample"]: row["reference"] for row in rows}
            histogram.hist(list(samples.values()), bins=20, color="#237a95")
            histogram.set(xlabel="Reference value (original units)", ylabel="Samples")
            fig.suptitle(f"{name} — PCA fit {prop['round']}")
            pdf.savefig(fig)
            filename = re.sub(r"[^\w. -]+", "_", name).strip(". ")
            if filename != name or not filename:
                filename = f"property_{index}_{filename}"
            fig.savefig(folder / f"{filename}_overview.png", dpi=180)


def calibration_label(measured, fitted):
    squared_error = float(np.sum((measured - fitted) ** 2))
    total = float(np.sum((measured - measured.mean()) ** 2))
    rmse = np.sqrt(squared_error / len(measured))
    values = {
        "R²": 1 - squared_error / total if total > 0 else None,
        "RMSE": rmse,
        "RPD": np.std(measured, ddof=1) / rmse if len(measured) > 1 and rmse > 0 else None,
        "RPIQ": (np.percentile(measured, 75) - np.percentile(measured, 25)) / rmse
        if rmse > 0
        else None,
    }
    details = "  |  ".join(
        f"{name} = {value:.4g}" if value is not None else f"{name} = N/A"
        for name, value in values.items()
    )
    return f"Calibration · displayed spectra (n={len(measured)})\n{details}"


def calibration_figures(state, folder):
    with PdfPages(folder / "Calibration_report.pdf") as pdf:
        for index, (name, prop) in enumerate(state["properties"].items()):
            for half in ("A", "B"):
                rows = prop["diagnostics"][half]["rows"]
                excluded = np.array([row["File Name"] in prop["decisions"] for row in rows])
                for scale, measured_key, prediction_key, units in (
                    (
                        "modelled",
                        "Transformed Reference",
                        "Transformed Prediction",
                        prop["config"]["transform"] + " scale",
                    ),
                    (
                        "original",
                        "Reference Value",
                        "Calibration Prediction",
                        prop["config"]["units"],
                    ),
                ):
                    measured = np.array([row[measured_key] for row in rows])
                    fitted = np.array([row[prediction_key] for row in rows])
                    fig = Figure(figsize=(8, 6), layout="constrained")
                    ax = fig.subplots()
                    lo = min(measured.min(), fitted.min())
                    hi = max(measured.max(), fitted.max())
                    ax.plot([lo, hi], [lo, hi], "k--", lw=1, label="1:1 line")
                    for mask, label, color in [
                        (~excluded, "Retained", "#238798"),
                        (excluded, "Excluded", "#b43f42"),
                    ]:
                        ax.scatter(measured[mask], fitted[mask], c=color, s=18, label=label)
                    ax.legend(loc="lower right", fontsize=8)
                    ax.text(
                        0.02,
                        0.98,
                        calibration_label(measured, fitted),
                        transform=ax.transAxes,
                        va="top",
                        fontsize=8,
                        bbox={"facecolor": "white", "alpha": 0.9},
                    )
                    suffix = f" ({units})" if units else ""
                    first = rows[0]
                    ax.set(
                        xlabel=f"Measured{suffix}",
                        ylabel=f"Calibration fit{suffix}",
                        title=(
                            f"{name} · Half {half} · rank {int(first['Diagnostic Rank'])}\n"
                            f"{first['Preprocessing']}"
                        ),
                    )
                    pdf.savefig(fig)
                    fig.savefig(folder / f"property_{index}_{half}_{scale}.png", dpi=160)


def write_figures(state, properties, folder):
    with FIGURE_LOCK:
        pca_figures(properties, folder)
        calibration_figures(state, folder)
