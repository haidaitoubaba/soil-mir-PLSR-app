from __future__ import annotations

import numpy as np


def measured_vs_predicted_figure(
    measured,
    predicted,
    *,
    title: str | None = None,
    predicted_label: str = "Predicted",
):
    """Create a measured-vs-predicted scatter plot with a true 1:1 reference line."""
    import matplotlib.pyplot as plt

    measured = np.asarray(
        measured,
        dtype=float,
    ).ravel()
    predicted = np.asarray(
        predicted,
        dtype=float,
    ).ravel()

    if measured.shape != predicted.shape:
        raise ValueError(
            "Measured and predicted values must have the same shape."
        )
    if measured.size == 0:
        raise ValueError(
            "Measured and predicted values must not be empty."
        )
    if (
        not np.isfinite(measured).all()
        or not np.isfinite(predicted).all()
    ):
        raise ValueError(
            "Measured and predicted values must be finite."
        )

    low = float(
        min(
            measured.min(),
            predicted.min(),
        )
    )
    high = float(
        max(
            measured.max(),
            predicted.max(),
        )
    )
    span = high - low
    pad = (
        span * 0.05
        if span > 0
        else max(
            abs(low) * 0.05,
            1e-6,
        )
    )
    axis_low = low - pad
    axis_high = high + pad

    fig, ax = plt.subplots(
        figsize=(7, 6),
    )
    ax.scatter(
        measured,
        predicted,
        alpha=0.7,
    )
    ax.plot(
        [axis_low, axis_high],
        [axis_low, axis_high],
        linestyle="--",
        label="1:1 line",
    )
    ax.set_xlim(
        axis_low,
        axis_high,
    )
    ax.set_ylim(
        axis_low,
        axis_high,
    )
    ax.set_aspect(
        "equal",
        adjustable="box",
    )
    ax.set_xlabel("Measured")
    ax.set_ylabel(predicted_label)
    if title:
        ax.set_title(title)
    ax.grid(
        alpha=0.2,
    )
    ax.legend()
    fig.tight_layout()
    return fig
