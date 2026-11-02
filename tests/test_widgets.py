"""@file test_widgets.py
@brief The widgets adapted from Tarea 1: SensorPlots' ring buffer and ReadingsPanel's
"no transmitida" / Δt display. Offscreen Qt (see conftest.py), slots called directly.
"""
import numpy as np
import pytest

from widgets.readings_panel import NOT_SENT, ReadingsPanel
from widgets.sensor_plots import SensorPlots


def test_sensor_plots_series_stays_chronological_across_the_wrap(qapp):
    """@brief After more samples than the ring holds, series() returns the newest ones in order."""
    plots = SensorPlots()
    cap = plots._cap
    for i in range(cap + 7):
        plots.push("T", i * 200, 20.0 + i)          # 5 Hz

    t, v = plots.series("T")
    assert len(t) == cap
    assert np.all(np.diff(t) > 0)
    assert t[-1] == pytest.approx((cap + 6) * 0.2)
    assert v[-1] == 20.0 + cap + 6
    assert plots.series("H")[0].size == 0           # other variables untouched


def test_sensor_plots_redraw_and_clear(qapp):
    """@brief The timer slot draws only dirty plots and clear() empties the buffers."""
    plots = SensorPlots()
    plots.push("P", 1000, 1012.5)
    plots.push("P", 2000, 1012.7)
    plots._redraw()
    x, y = plots._curves["P"].getData()
    assert list(y) == [1012.5, 1012.7]

    plots.clear()
    assert plots.series("P")[0].size == 0


def test_sensor_plots_marks_untransmitted_variables(qapp):
    """@brief A deselected variable is recognisable from its plot title (spec 4)."""
    plots = SensorPlots()
    plots.set_transmitted("H", False)
    assert "no transmitida" in plots._plots["H"].plotItem.titleLabel.text
    plots.set_transmitted("H", True)
    assert "no transmitida" not in plots._plots["H"].plotItem.titleLabel.text


def test_readings_panel_shows_missing_variables_as_not_transmitted(qapp):
    """@brief Only the variables in the packet show a value; Δt comes from ESP32 timestamps."""
    panel = ReadingsPanel()
    panel.update_sample(1, 1000, {"T": 26.4, "P": 1012.7})
    assert panel.value_labels["T"].text() == "26.40 °C"
    assert panel.value_labels["H"].text() == NOT_SENT
    assert not panel.value_labels["H"].isEnabled()
    assert panel.value_labels["P"].text() == "1012.70 hPa"

    panel.update_sample(2, 1200, {"H": 45.0})
    assert "Δt 200 ms" in panel.timing_label.text()
    assert panel.value_labels["T"].text() == NOT_SENT
    assert panel.value_labels["H"].text() == "45.0 %HR"

    panel.clear()
    assert panel.timing_label.text() == "sin datos"
    assert panel.value_labels["T"].text() == "--"
