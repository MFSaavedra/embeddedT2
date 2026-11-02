"""@file test_widgets.py
@brief The panels and plots: what they show for each kind of data, and the configuration
panel's rules. Offscreen Qt (see conftest.py), slots called directly.
"""
import numpy as np
import pytest

from messages import Config, Peak, Sample
from widgets.config_panel import ConfigPanel
from widgets.peak_panel import PeakPanel
from widgets.readings_panel import NOT_SENT, ReadingsPanel
from widgets.sensor_plots import SensorPlots

# ------------------------------------ plots ------------------------------------


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
    _x, y = plots._curves["P"].getData()
    assert list(y) == [1012.5, 1012.7]

    plots.clear()
    assert plots.series("P")[0].size == 0


def test_sensor_plots_break_the_line_across_gaps(qapp):
    """@brief A stretch without samples (variable not transmitted) is not bridged by a line."""
    plots = SensorPlots()
    plots.push("H", 1000, 50.0)
    plots.push("H", 2000, 50.1)                     # 1 Hz: one segment
    plots.push("H", 10000, 50.2)                    # 8 s later: a gap
    _t, v = plots.series("H")
    assert len(v) == 4 and np.isnan(v[2]) and v[3] == 50.2


def test_sensor_plots_marks_untransmitted_variables(qapp):
    """@brief A deselected variable is recognisable from its plot title (spec 4)."""
    plots = SensorPlots()
    plots.set_transmitted("H", False)
    assert "no transmitida" in plots._plots["H"].plotItem.titleLabel.text
    plots.set_transmitted("H", True)
    assert "no transmitida" not in plots._plots["H"].plotItem.titleLabel.text


def test_sensor_plots_draw_the_esp32_results_on_the_temperature_plot(qapp):
    """@brief Average curve, peak markers and θ line, even with T itself hidden (spec 6.6)."""
    plots = SensorPlots()
    plots.push("avg", 1000, 24.1)
    plots.push("avg", 2000, 24.2)
    plots._redraw()
    _x, y = plots._curves["avg"].getData()
    assert list(y) == [24.1, 24.2]
    assert plots._plots["T"].getViewBox().viewRange()[0][1] == pytest.approx(2.0)

    plots.add_peak(1500, 25.3)
    x, y = plots._peak_markers.getData()
    assert list(x) == [1.5] and list(y) == [25.3]

    plots.set_threshold(True, 24.5)
    assert plots._theta_line.isVisible() and plots._theta_line.value() == 24.5
    plots.set_threshold(False, 24.5)
    assert not plots._theta_line.isVisible()

    plots.clear()
    assert plots._peak_markers.getData()[0].size == 0

# ---------------------------------- readings -----------------------------------


def test_readings_panel_shows_missing_variables_as_not_transmitted(qapp):
    """@brief Only the variables in the packet show a value; Δt comes from ESP32 timestamps."""
    panel = ReadingsPanel()
    panel.update_sample(Sample(1, 1000, {"T": 26.4, "P": 1012.7}))
    assert panel.value_labels["T"].text() == "26.40 °C"
    assert panel.value_labels["H"].text() == NOT_SENT
    assert not panel.value_labels["H"].isEnabled()
    assert panel.value_labels["P"].text() == "1012.70 hPa"
    assert panel.state_label.text() == "Lectura válida"

    panel.update_sample(Sample(2, 1200, {"H": 45.0}))
    assert "Δt 200 ms" in panel.timing_label.text()
    assert panel.value_labels["T"].text() == NOT_SENT
    assert panel.value_labels["H"].text() == "45.00 %HR"

    panel.clear()
    assert panel.state_label.text() == "sin datos"
    assert panel.value_labels["T"].text() == "--"


def test_readings_panel_flags_invalid_readings_and_silence(qapp):
    """@brief Spec 4, "Resultados": an invalid reading and a silent link are both visible."""
    panel = ReadingsPanel()
    panel.update_sample(Sample(1, 1000, {}, error="no_sensor"))
    assert "INVÁLIDA" in panel.state_label.text() and "no_sensor" in panel.state_label.text()
    assert panel.value_labels["T"].text() == "inválida"

    panel.update_sample(Sample(2, 2000, {"T": 24.0}))
    assert panel.state_label.text() == "Lectura válida"
    panel.set_no_data()
    assert panel.state_label.text().startswith("SIN DATOS")
    assert not panel.value_labels["T"].isEnabled()


def test_readings_panel_counts_lost_frames_from_seq_gaps(qapp):
    """@brief A jump in seq is a frame lost on the link (failed readings keep their seq)."""
    panel = ReadingsPanel()
    for seq in (0, 1, 4, 5):
        panel.update_sample(Sample(seq, seq * 1000, {"P": 950.0}))
    assert "perdidos 2" in panel.timing_label.text()


def test_readings_panel_validates_the_esp32_average_on_the_pc(qapp):
    """@brief Spec 4: the PC recomputes the average only to check it, labelled as such."""
    panel = ReadingsPanel()
    panel.set_avg_config(True, 5)
    temps = [24.0, 24.2, 24.4, 24.6, 24.8, 25.0, 25.2]
    for i, temp in enumerate(temps):
        window = [t for k, t in enumerate(temps[:i + 1]) if i - 5 < k]   # (t - 5 s, t]
        avg = round(sum(window) / len(window), 2)
        panel.update_sample(Sample(i, i * 1000, {"T": temp}, avg_c=avg, avg_n=len(window),
                                   avg_complete=i >= 5))
    assert "Promedio T (ESP32): 24.80 °C" in panel.avg_label.text()
    assert "N = 5" in panel.avg_label.text() and "ventana completa" in panel.avg_label.text()
    assert "Validación PC (solo verificación): 24.80 °C" in panel.check_label.text()
    assert "diferencia +0.00" in panel.check_label.text()

    panel.update_sample(Sample(7, 7000, {"H": 50.0}, avg_c=25.0, avg_n=5, avg_complete=True))
    assert "T no se transmite" in panel.check_label.text()

    panel.set_avg_config(False, 5)
    assert "desactivado" in panel.avg_label.text()

# ----------------------------------- peaks -------------------------------------


def test_peak_panel_keeps_a_history_newest_first(qapp):
    """@brief Spec 3.2: history of peak events plus the threshold in force."""
    panel = PeakPanel()
    panel.set_threshold(True, 24.5)
    assert "24.5 °C" in panel.threshold_label.text()
    assert "activada" in panel.threshold_label.text()

    panel.add_peak(Peak(10000, 25.31, 24.5))
    panel.add_peak(Peak(42000, 26.02, 24.5))
    assert panel.table.rowCount() == 2
    assert panel.table.item(0, 0).text() == "42.000"
    assert panel.table.item(0, 2).text() == "26.02"
    assert panel.table.item(1, 3).text() == "24.5"

    panel.clear_btn.click()
    assert panel.table.rowCount() == 0

# ------------------------------- configuration ---------------------------------


def test_config_panel_starts_on_the_firmware_defaults(qapp):
    """@brief The controls and the confirmed line both start at app_config.h's defaults."""
    panel = ConfigPanel()
    assert panel.config() == Config()
    assert panel.confirmed_label.text() == Config().describe()


def test_config_panel_cannot_select_no_variable(qapp):
    """@brief Spec 2.2: an empty selection is prevented, the last ticked box is locked."""
    panel = ConfigPanel()
    panel.var_checks["T"].setChecked(False)
    panel.var_checks["H"].setChecked(False)
    assert panel.config().variables == "P"
    assert not panel.var_checks["P"].isEnabled()

    panel.var_checks["H"].setChecked(True)
    assert panel.var_checks["P"].isEnabled()
    assert panel.config().variables == "HP"


def test_config_panel_apply_emits_one_config(qapp):
    """@brief Aplicar emits the whole configuration; θ keeps 0.1 °C resolution."""
    panel = ConfigPanel()
    got = []
    panel.apply_requested.connect(got.append)
    wanted = Config(sampling_hz=5.0, variables="HP", avg_enabled=True, window_s=30,
                    peak_enabled=True, threshold_c=24.7)
    panel.set_controls(wanted)
    panel.apply_btn.click()
    assert got == [wanted]
    assert got[0].payload().endswith("threshold_c=24.7")


def test_config_panel_shows_pending_confirmed_and_rejected(qapp):
    """@brief The panel never claims a configuration the ESP32 did not confirm."""
    panel = ConfigPanel()
    panel.set_pending()
    assert "esperando" in panel.state_label.text()

    cfg = Config(sampling_hz=2.0, variables="T")
    panel.set_confirmed(cfg)
    assert panel.state_label.text() == "confirmada por el ESP32"
    assert panel.confirmed_label.text() == cfg.describe()

    panel.set_rejected("BADARG,sampling_hz")
    assert "RECHAZADA" in panel.state_label.text() and "sampling_hz" in panel.state_label.text()
    assert panel.confirmed_label.text() == cfg.describe()     # still the previous one
