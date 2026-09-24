import numpy as np
import pytest

from soil_mir.plotting import (
    measured_vs_predicted_figure,
)


def test_measured_vs_predicted_plot_has_one_to_one_line_and_equal_limits():
    measured = np.array(
        [1.0, 2.0, 3.0]
    )
    predicted = np.array(
        [1.2, 1.8, 3.4]
    )

    fig = measured_vs_predicted_figure(
        measured,
        predicted,
        title="Validation",
    )
    ax = fig.axes[0]

    assert len(ax.collections) == 1
    assert len(ax.lines) == 1

    line = ax.lines[0]
    np.testing.assert_allclose(
        line.get_xdata(),
        line.get_ydata(),
    )
    assert line.get_label() == "1:1 line"

    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    np.testing.assert_allclose(
        xlim,
        ylim,
    )
    assert ax.get_aspect() == pytest.approx(1.0)


def test_measured_vs_predicted_plot_rejects_invalid_data():
    with pytest.raises(
        ValueError,
        match="same shape",
    ):
        measured_vs_predicted_figure(
            [1.0, 2.0],
            [1.0],
        )

    with pytest.raises(
        ValueError,
        match="finite",
    ):
        measured_vs_predicted_figure(
            [1.0, np.nan],
            [1.0, 2.0],
        )
