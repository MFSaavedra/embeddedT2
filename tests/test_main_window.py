"""@file test_main_window.py
@brief MainWindow against a stub worker: the baud renegotiation state machine (from T1), and
the T2 routing of SMP / PEAK / ACK,CFG / ERR, the CFG lifecycle, the "sin datos" watchdog
and the automatic reconnection.

Offscreen Qt (see conftest.py), no serial port and no event loop: the test plays the part
of the firmware by calling the slots that SerialWorker's signals would call, and checks
what MainWindow sends and how it leaves the panels.
"""
import pytest
from PyQt5.QtCore import QObject, pyqtSignal

import main_window as mw
import widgets.connection_panel as cp
from messages import Config


class StubWorker(QObject):
    """@brief SerialWorker stand-in: same signals, records what was sent."""

    frame_received = pyqtSignal(list)
    bad_line = pyqtSignal(str)
    connected = pyqtSignal(str, int)
    disconnected = pyqtSignal()
    baud_changed = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        ## Payloads passed to send(), in order.
        self.sent = []
        ## Baud rates passed to request_baud(), in order.
        self.baud_requests = []
        ## (port, baud) passed to open(), in order.
        self.opened = []
        ## What open() returns next.
        self.open_result = True

    def send(self, payload):
        self.sent.append(payload)
        return True

    def request_baud(self, baud):
        self.baud_requests.append(baud)

    def open(self, port, baud):
        self.opened.append((port, baud))
        return self.open_result

    def close(self):
        pass


@pytest.fixture
def fresh_window(qapp, monkeypatch):
    """@brief A MainWindow wired to a StubWorker, still disconnected."""
    monkeypatch.setattr(mw, "SerialWorker", StubWorker)
    return mw.MainWindow()


@pytest.fixture
def window(fresh_window):
    """@brief A MainWindow already "connected" at the boot speed."""
    fresh_window._on_connected("FAKE", cp.DEFAULT_BAUD)
    return fresh_window


def _pick_baud(window, baud):
    """@brief Choose @p baud in the panel, as a user would."""
    combo = window.connection.baud_combo
    combo.setCurrentIndex(combo.findData(baud))


def test_successful_renegotiation(window):
    """@brief Selector -> BAUD -> ACK,BAUD -> switch -> INIT -> ACK,INIT completes the change."""
    _pick_baud(window, 230400)
    assert window.worker.sent == ["BAUD,230400"]
    assert window._baud_pending == 230400
    # Locked while in flight: a second switch, or an INIT written at the speed the firmware
    # has already left, would land in the middle of the changeover.
    assert not window.connection.baud_combo.isEnabled()
    assert not window.connection.init_btn.isEnabled()

    # The firmware answers at the old speed, then switches; the PC follows.
    window._on_frame(["ACK", "BAUD", "230400"])
    assert window.worker.baud_requests == [230400]

    # The worker reports the port is at the new speed: INIT proves it to the firmware.
    window._on_baud_changed(230400)
    assert window.worker.sent == ["BAUD,230400", "INIT"]
    assert window._baud_pending == 230400                 # not committed yet

    window._on_frame(["ACK", "INIT", "2.0"])
    assert window._baud == 230400
    assert window._baud_pending is None
    assert window.connection.baud_combo.isEnabled()
    assert window.connection.init_btn.isEnabled()
    assert not window._baud_timer.isActive()


def test_timeout_falls_back_to_the_previous_speed(window):
    """@brief Nothing comes back at the new speed: the PC returns to where the firmware
    will also have reverted (LINK_BAUD_REVERT_MS)."""
    _pick_baud(window, 115200)
    window._on_frame(["ACK", "BAUD", "115200"])
    window._on_baud_changed(115200)

    window._on_baud_timeout()

    assert window.worker.baud_requests == [115200, 921600]
    assert window._baud == 921600
    assert window._baud_pending is None
    assert window.connection.baud_combo.currentData() == 921600
    assert window.connection.baud_combo.isEnabled()
    assert window.connection.init_btn.isEnabled()   # usable again to restart the streaming


def test_err_aborts_without_waiting_for_the_timeout(window):
    """@brief A refused rate is handled on the spot: the firmware never switched."""
    _pick_baud(window, 460800)
    window._on_frame(["ERR", "BADARG"])

    assert window._baud == 921600
    assert window._baud_pending is None
    assert window.connection.baud_combo.currentData() == 921600
    assert not window._baud_timer.isActive()


def test_selecting_a_speed_before_connecting_renegotiates_on_connect(fresh_window):
    """@brief The selector means the same thing whenever it is touched.

    Picking a speed while disconnected must not become the speed the port is opened at - the
    board boots into LINK_BAUD, so that would open a mute connection. It is remembered and
    applied by renegotiating once the link is up.
    """
    w = fresh_window
    _pick_baud(w, 230400)
    assert w.worker.sent == []                       # nothing to talk to yet

    w._on_connected("FAKE", cp.DEFAULT_BAUD)         # the worker always opens at boot speed

    assert w.worker.sent == ["BAUD,230400"]
    assert w._baud_pending == 230400


def test_connecting_at_the_selected_speed_renegotiates_nothing(fresh_window):
    """@brief The common case must stay silent."""
    fresh_window._on_connected("FAKE", cp.DEFAULT_BAUD)
    assert fresh_window.worker.sent == []
    assert fresh_window._baud_pending is None


def test_disconnect_keeps_the_selected_speed(window):
    """@brief The choice survives a disconnect; the next connect renegotiates back to it."""
    _pick_baud(window, 230400)
    window._on_frame(["ACK", "BAUD", "230400"])
    window._on_baud_changed(230400)
    window._on_frame(["ACK", "INIT", "2.0"])
    assert window._baud == 230400

    window._on_disconnected()
    assert window.connection.baud_combo.currentData() == 230400
    assert window._baud == 0

    window.worker.sent.clear()
    window._on_connected("FAKE", cp.DEFAULT_BAUD)
    assert window.worker.sent == ["BAUD,230400"]


def test_reselecting_the_current_speed_sends_nothing(window):
    """@brief Landing back on the speed already in use must not start a renegotiation."""
    _pick_baud(window, 230400)
    window._on_frame(["ACK", "BAUD", "230400"])
    window._on_baud_changed(230400)
    window._on_frame(["ACK", "INIT", "2.0"])
    window.worker.sent.clear()

    _pick_baud(window, 230400)
    assert window.worker.sent == []


# ------------------------------- T2: incoming data -------------------------------


def _frame(line):
    """@brief Split a payload as SerialWorker.frame_received would deliver it."""
    return line.split(",")


@pytest.fixture
def running(window):
    """@brief A connected window whose ESP32 has acknowledged INIT (acquiring, defaults)."""
    window._on_frame(_frame("ACK,INIT,2.0"))
    window.worker.sent.clear()
    return window


def test_sample_reaches_readings_plots_and_counters(running):
    """@brief An SMP updates the values, feeds the plots (average included) and counts OK."""
    ok = running._frames_ok
    running._on_frame(_frame("SMP,seq=0,t_ms=2044,temperature_c=24.09,pressure_hpa=952.25,"
                             "temp_avg_c=24.09,avg_n=1,avg_window_complete=0"))
    assert running.readings.value_labels["T"].text() == "24.09 °C"
    assert running.readings.value_labels["H"].text() == "no transmitida"
    assert list(running.plots.series("P")[1]) == [952.25]
    assert list(running.plots.series("avg")[1]) == [24.09]
    assert running._frames_ok == ok + 1


def test_malformed_sample_counts_as_rejected_and_changes_nothing(running):
    """@brief T1 rule: valid checksum, unusable fields -> rejected, not OK."""
    ok, bad = running._frames_ok, running._frames_bad
    running._on_frame(_frame("SMP,seq=1,t_ms=3044,temperature_c=caliente"))
    running._on_frame(_frame("NEWS,hello"))                       # unknown type
    assert (running._frames_ok, running._frames_bad) == (ok, bad + 2)
    assert running.plots.series("T")[0].size == 0


def test_invalid_reading_is_shown_and_not_plotted(running):
    """@brief Spec 2.1.2 end to end: an error SMP plots nothing and says so."""
    running._on_frame(_frame("SMP,seq=0,t_ms=1000,error=no_sensor"))
    assert "INVÁLIDA" in running.readings.state_label.text()
    assert running.plots.series("T")[0].size == 0


def test_no_data_watchdog_follows_the_confirmed_rate(running):
    """@brief "sin datos" after NO_DATA_PERIODS periods of the rate the ESP32 confirmed."""
    running._on_frame(_frame("SMP,seq=0,t_ms=1000,temperature_c=24.0"))
    assert running._data_timer.isActive() and running._data_timer.interval() == 2500
    running._on_frame(_frame("ACK,CFG,sampling_hz=5,variables=T,avg_enabled=0,window_s=10,"
                             "peak_enabled=0,threshold_c=28.0"))
    running._on_frame(_frame("SMP,seq=1,t_ms=1200,temperature_c=24.0"))
    assert running._data_timer.interval() == 500

    running._data_timer.timeout.emit()
    assert running.readings.state_label.text().startswith("SIN DATOS")


def test_peak_goes_to_the_history_and_the_plot(running):
    """@brief A PEAK frame becomes a history row and a marker on the temperature plot."""
    running._on_frame(_frame("PEAK,t_ms=75410,peak_c=28.70,threshold_c=28.0"))
    assert running.peaks.table.rowCount() == 1
    assert running.peaks.table.item(0, 2).text() == "28.70"
    assert list(running.plots._peak_markers.getData()[1]) == [28.7]

# ------------------------------ T2: configuration -------------------------------


def test_config_is_pending_until_the_esp32_confirms_it(running):
    """@brief Aplicar sends one CFG; only the ACK,CFG echo changes what the GUI shows."""
    panel = running.config_panel
    cfg = Config(sampling_hz=2.0, variables="TP", avg_enabled=True, window_s=10,
                 peak_enabled=True, threshold_c=24.5)
    panel.set_controls(cfg)
    panel.apply_btn.click()
    assert running.worker.sent == [cfg.payload()]
    assert "esperando" in panel.state_label.text()
    assert running._confirmed == Config()                      # nothing assumed yet

    running._on_frame(_frame("ACK," + cfg.payload()))          # the firmware echoes it
    assert running._confirmed == cfg
    assert panel.state_label.text() == "confirmada por el ESP32"
    assert "no transmitida" in running.plots._plots["H"].plotItem.titleLabel.text
    assert running.plots._theta_line.isVisible() and running.plots._theta_line.value() == 24.5
    assert "24.5 °C" in running.peaks.threshold_label.text()


def test_rejected_config_keeps_the_previous_one(running):
    """@brief Spec 6.7: an invalid configuration is rejected visibly, nothing changes."""
    running.command_box.entry.setText(
        "CFG,sampling_hz=3,variables=T,avg_enabled=0,window_s=10,peak_enabled=0,threshold_c=28.0")
    running.command_box.send_btn.click()
    assert running.worker.sent[-1].startswith("CFG,sampling_hz=3")
    running._on_frame(_frame("ERR,BADARG,sampling_hz"))
    assert "RECHAZADA" in running.config_panel.state_label.text()
    assert running._confirmed == Config()
    assert running._cfg_pending is False


def test_manual_box_refuses_baud_and_non_ascii(running):
    """@brief BAUD must go through the selector; non-ASCII text cannot be framed."""
    running._send_manual("BAUD,115200")
    running._send_manual("CFG,θ")
    assert running.worker.sent == []


def test_init_ack_resets_the_panels_to_the_defaults(running):
    """@brief After INIT the firmware is on its defaults, and so is every panel."""
    running.config_panel.set_controls(Config(sampling_hz=5.0, variables="H"))
    running._on_frame(_frame("ACK,CFG,sampling_hz=5,variables=H,avg_enabled=0,window_s=10,"
                             "peak_enabled=0,threshold_c=28.0"))
    running._on_frame(_frame("ACK,INIT,2.0"))
    assert running.config_panel.config() == Config()
    assert running._confirmed == Config()
    assert "adquiriendo (firmware 2.0)" in running.connection.status_label.text()

# ------------------------------- T2: reconnection --------------------------------


def _connected_session(fresh_window):
    """@brief Connect through the panel's path and confirm a non-default configuration."""
    w = fresh_window
    w._connect("FAKE", cp.DEFAULT_BAUD)
    w._on_connected("FAKE", cp.DEFAULT_BAUD)
    w._on_frame(_frame("ACK,INIT,2.0"))
    cfg = Config(sampling_hz=5.0, variables="HP", avg_enabled=True, window_s=5)
    w._on_frame(_frame("ACK," + cfg.payload()))
    w.worker.sent.clear()
    return w, cfg


def test_lost_link_is_retried_and_the_session_restored(fresh_window):
    """@brief Spec 6.7: cable pulled -> retries -> reconnect -> INIT -> same configuration."""
    w, cfg = _connected_session(fresh_window)

    w._on_disconnected()                                       # the port died under us
    assert w._reconnect_timer.isActive()
    assert w.connection.connect_btn.text() == "Cancelar reconexión"
    assert "CONEXIÓN PERDIDA" in w.connection.status_label.text()
    assert not w.config_panel.isEnabled()

    w.worker.open_result = False                               # still unplugged
    w._try_reconnect()
    assert w._reconnect_timer.isActive()
    w.worker.open_result = True                                # plugged back in
    w._try_reconnect()
    assert not w._reconnect_timer.isActive()
    assert w.worker.opened[-1] == ("FAKE", cp.DEFAULT_BAUD)

    w._on_connected("FAKE", cp.DEFAULT_BAUD)                   # board reset, booted
    assert w.worker.sent == ["INIT"]
    w._on_frame(_frame("ACK,INIT,2.0"))
    assert w.worker.sent == ["INIT", cfg.payload()]            # the session comes back
    w._on_frame(_frame("ACK," + cfg.payload()))
    assert w._confirmed == cfg


def test_user_disconnect_is_not_retried(fresh_window):
    """@brief Desconectar means it: no retries, no restore on the next connect."""
    w, _cfg = _connected_session(fresh_window)
    w._disconnect()
    w._on_disconnected()                                       # what the worker then emits
    assert not w._reconnect_timer.isActive()
    assert w.connection.connect_btn.text() == "Conectar"

    w._connect("FAKE", cp.DEFAULT_BAUD)
    w._on_connected("FAKE", cp.DEFAULT_BAUD)
    assert w.worker.sent == []                                 # waits for Inicializar


def test_cancelling_the_reconnection_stops_the_retries(fresh_window):
    """@brief Cancelar reconexión (the same button) stops retrying."""
    w, _cfg = _connected_session(fresh_window)
    w._on_disconnected()
    w.connection.connect_btn.click()                           # "Cancelar reconexión"
    assert not w._reconnect_timer.isActive()
    assert w.connection.connect_btn.text() == "Conectar"
    assert w.connection.port_combo.isEnabled()


def test_baud_change_restores_the_configuration(running):
    """@brief The INIT that ends a renegotiation resets the firmware: the config is re-sent."""
    cfg = Config(variables="T", peak_enabled=True, threshold_c=24.0)
    running._on_frame(_frame("ACK," + cfg.payload()))
    running.worker.sent.clear()
    _pick_baud(running, 230400)
    running._on_frame(_frame("ACK,BAUD,230400"))
    running._on_baud_changed(230400)
    running._on_frame(_frame("ACK,INIT,2.0"))
    assert running.worker.sent == ["BAUD,230400", "INIT", cfg.payload()]
    assert running._baud == 230400
