"""@file main_window.py
@brief Main window: wires the panels, the plots and the serial worker together.

Data flow (carried over from Tarea 1; the T2 panels plug into the same two paths):

    panels ──(Qt signals)──▶ MainWindow._send_*()  ──▶ SerialWorker.send(payload)
    SerialWorker.frame_received ──▶ MainWindow._on_frame(fields) ──▶ readings / plots / peaks / status bar
    SerialWorker.baud_changed   ──▶ MainWindow._on_baud_changed  ──▶ SerialWorker.send("INIT")

messages.py gives the T2 fields their meaning: Config builds CFG and decodes the ACK,CFG
echo; parse_sample() and parse_peak() decode SMP and PEAK.

Nothing here touches pyserial directly and nothing in serial_worker.py touches widgets: the
worker is told *when* to change the link speed but never learns what a BAUD frame is.

Three rules this file keeps:
- Nothing is assumed applied before the ESP32 confirms it: the panels follow ACK,CFG and
  ACK,INIT, never the command that was sent (spec 9).
- The average and the peaks shown come from the ESP32. The PC only recomputes the average to
  validate it, labelled as such (ReadingsPanel).
- A link that dies without the user asking is retried every RECONNECT_INTERVAL_MS. The board
  restarts with its defaults when the port reopens, so if it was acquiring, the GUI sends
  INIT and then the configuration that was confirmed before the loss.
"""
from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QVBoxLayout, QWidget

import messages
import protocol
from messages import Config
from serial_worker import SerialWorker, available_ports
from widgets.command_box import CommandBox
from widgets.config_panel import ConfigPanel
from widgets.connection_panel import DEFAULT_BAUD, ConnectionPanel
from widgets.peak_panel import PeakPanel
from widgets.readings_panel import ReadingsPanel
from widgets.sensor_plots import SensorPlots

## How long to wait for a baud renegotiation to complete before giving up, ms. Must exceed
## LINK_BAUD_REVERT_MS in app_config.h so the firmware has already fallen back by then and
## both ends land on the same speed.
BAUD_NEGOTIATION_MS = 8000
## Sampling periods without an SMP after which the readings are flagged "sin datos".
NO_DATA_PERIODS = 2.5
## Interval between attempts to reopen a port that died, ms.
RECONNECT_INTERVAL_MS = 1000


class MainWindow(QMainWindow):
    """@brief Top-level window: controls on the left; readings, peaks and plots on the right.

    Owns the SerialWorker and translates between widget signals and protocol payloads in
    both directions. Also keeps the valid / rejected frame counters shown in the status bar.
    """

    def __init__(self, parent=None):
        """@brief Build the widgets, lay them out and connect every signal.

        @param parent  Optional QWidget parent.
        """
        super().__init__(parent)
        self.setWindowTitle("Tarea 2 CC5328 — BME688 y procesamiento local en ESP32")

        ## Serial I/O thread (see serial_worker.py).
        self.worker = SerialWorker(self)
        ## Port / baud / connect / init panel (spec 4, "Conexión").
        self.connection = ConnectionPanel()
        ## Rate, variables, average and peaks, sent as one CFG (spec 4, "Configuración" and
        ## "Procesamiento local").
        self.config_panel = ConfigPanel()
        ## Manual command entry, to send an invalid command on purpose (spec 6.7).
        self.command_box = CommandBox()
        ## Latest T / H / P values, the ESP32's average and the stream state (spec 4,
        ## "Visualización" and "Resultados").
        self.readings = ReadingsPanel()
        ## Peak event history and the threshold in force (spec 3.2).
        self.peaks = PeakPanel()
        ## T / H / P history plots, with the average, θ and the peaks on T (spec 4).
        self.plots = SensorPlots()

        # ---- layout: controls on the left; readings + peaks above the plots on the right ----
        left = QVBoxLayout()
        left.addWidget(self.connection)
        left.addWidget(self.config_panel)
        left.addWidget(self.command_box)
        left.addStretch(1)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMinimumWidth(400)
        left_widget.setMaximumWidth(500)

        top = QHBoxLayout()
        top.addWidget(self.readings, 3)
        top.addWidget(self.peaks, 2)
        right = QVBoxLayout()
        right.addLayout(top)
        right.addWidget(self.plots, 1)

        root = QHBoxLayout()
        root.addWidget(left_widget)
        root.addLayout(right, 1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        ## Frames that passed the checksum and were understood.
        self._frames_ok = 0
        ## Lines that were not frames, failed the checksum, or had malformed fields.
        self._frames_bad = 0
        ## Speed the link is currently running at, on both ends.
        self._baud = 0
        ## Speed asked for by a BAUD command that has not completed yet, else None.
        self._baud_pending: Optional[int] = None
        ## Gives up on a renegotiation that neither succeeds nor is refused.
        self._baud_timer = QTimer(self)
        self._baud_timer.setSingleShot(True)
        ## Configuration the ESP32 confirmed last (its defaults until told otherwise).
        self._confirmed = Config()
        ## True between sending a CFG and its ACK or ERR.
        self._cfg_pending = False
        ## True while the firmware acquires: from ACK,INIT until BAUD, a reset or a lost link.
        self._acquiring = False
        ## Configuration to re-send after the next ACK,INIT, when that INIT was not the user's
        ## (automatic reconnection, baud change); None otherwise.
        self._restore_cfg: Optional[Config] = None
        ## Firmware version from the last ACK,INIT ("" until one arrives).
        self._fw_version = ""
        ## Device name of the port the user connected to; reused by the reconnection.
        self._port = ""
        ## True from a successful Conectar until Desconectar: a disconnect while this is set
        ## was not asked for, so the link is retried.
        self._want_connected = False
        ## Retries a lost link every RECONNECT_INTERVAL_MS.
        self._reconnect_timer = QTimer(self)
        ## Reconnection attempts so far, for the status text.
        self._reconnect_attempts = 0
        ## Fires when no SMP arrived for NO_DATA_PERIODS sampling periods.
        self._data_timer = QTimer(self)
        self._data_timer.setSingleShot(True)
        ## Status-bar label showing both counters.
        self._counter_label = QLabel()
        self.statusBar().addPermanentWidget(self._counter_label)
        self._update_counters()

        # ---- wiring (hidden from Doxygen, which would read each self._callback as an attribute) ----
        # @cond
        self.connection.refresh_requested.connect(self._refresh_ports)
        self.connection.connect_requested.connect(self._connect)
        self.connection.disconnect_requested.connect(self._disconnect)
        self.connection.init_requested.connect(self._send_init)
        self.connection.baud_change_requested.connect(self._request_baud_change)
        self.config_panel.apply_requested.connect(self._send_config)
        self.command_box.command_entered.connect(self._send_manual)
        self._baud_timer.timeout.connect(self._on_baud_timeout)
        self._reconnect_timer.timeout.connect(self._try_reconnect)
        self._data_timer.timeout.connect(self.readings.set_no_data)

        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.error.connect(self._on_error)
        self.worker.baud_changed.connect(self._on_baud_changed)
        self.worker.frame_received.connect(self._on_frame)
        self.worker.bad_line.connect(self._on_bad_line)
        # @endcond

        self._set_controls_enabled(False)
        self._refresh_ports()

    # ------------------------------ connection ------------------------------

    def _refresh_ports(self) -> None:
        """@brief Rescan the serial ports and refill the connection panel's port list."""
        self.connection.set_ports(available_ports())

    def _connect(self, port: str, baud: int) -> None:
        """@brief Ask the worker to open @p port at @p baud (result arrives via signals).

        The worker resets the board and waits for it to boot before emitting connected,
        so the panel shows an intermediate message for about a second.

        @param port  Device name chosen in the connection panel.
        @param baud  Speed to open at, always the boot speed (see ConnectionPanel); a
                     different selection is applied afterwards by _on_connected().
        """
        if self.worker.open(port, baud):
            self._port = port
            self._want_connected = True
            self._restore_cfg = None        # connecting by hand starts a fresh session
            self.connection.set_connected(False, f"Conectando a {port}… (reiniciando ESP32)")

    def _disconnect(self) -> None:
        """@brief The user pressed Desconectar or Cancelar reconexión: close, stop retrying."""
        self._want_connected = False
        self._restore_cfg = None
        self._reconnect_timer.stop()
        self.connection.set_reconnecting(False)
        self.worker.close()
        self.connection.set_connected(False)

    def _on_connected(self, port: str, baud: int) -> None:
        """@brief Port open and board rebooted: enable the controls and clear stale data.

        The port was opened at the board's boot speed. If the user asked for a different one
        - before connecting, or during an earlier session - the link is renegotiated now, so
        the selector means the same thing whenever it is touched. After an automatic
        reconnection the interrupted session is resumed with INIT (the renegotiation sends
        one too), and _on_init_ack() then re-sends the configuration.

        @param port  Device name that was opened.
        @param baud  Baud rate the port was opened at.
        """
        self._baud = baud
        self._acquiring = False         # the board was just reset: it waits for INIT
        self._fw_version = ""
        self._reconnect_timer.stop()
        self.connection.set_reconnecting(False)
        self.connection.set_connected(True, self._status_text())
        self._set_controls_enabled(True)
        self.readings.clear()
        self.plots.clear()
        target = self.connection.target_baud()
        if target != baud:
            self._request_baud_change(target)
        elif self._restore_cfg is not None:
            self._send_init()

    def _on_disconnected(self) -> None:
        """@brief Port closed, by the user or by an error: disable the controls.

        If the user did not ask for it (cable pulled, board reset by hand, port error), the
        link is retried every RECONNECT_INTERVAL_MS until it comes back or the user cancels,
        remembering the configuration to restore (spec 6.7).

        The baud selector keeps whatever the user chose: it is a preference, not the speed
        the port is opened at, so the next connect opens at the boot speed and renegotiates
        back to it by itself.
        """
        self._baud_timer.stop()
        self._baud_pending = None
        self._baud = 0
        self._cfg_pending = False
        self._data_timer.stop()
        self.connection.set_busy(False)
        self.connection.set_connected(False)
        self._set_controls_enabled(False)
        self.readings.set_no_data()
        if self._want_connected:
            if self._acquiring:
                self._restore_cfg = self._confirmed
            self._reconnect_attempts = 0
            self.connection.set_reconnecting(
                True, f"CONEXIÓN PERDIDA con {self._port}. Reintentando…")
            self._reconnect_timer.start(RECONNECT_INTERVAL_MS)
        self._acquiring = False

    def _try_reconnect(self) -> None:
        """@brief Timer slot: try to reopen the lost port (connected follows if it works)."""
        self._reconnect_attempts += 1
        self.connection.set_reconnecting(
            True, f"CONEXIÓN PERDIDA con {self._port}. "
                  f"Reintentando (intento {self._reconnect_attempts})…")
        if self.worker.open(self._port, DEFAULT_BAUD):
            self._reconnect_timer.stop()
            self.connection.set_reconnecting(
                False, f"Reconectando a {self._port}… (reiniciando ESP32)")

    def _on_error(self, message: str) -> None:
        """@brief Show a worker error in the status bar for 5 s.

        @param message  Human-readable text from SerialWorker.error.
        """
        self.statusBar().showMessage(message, 5000)

    def _set_controls_enabled(self, enabled: bool) -> None:
        """@brief Enable the panels that send commands, only while connected.

        @param enabled  True while a port is open.
        """
        self.config_panel.setEnabled(enabled)
        self.command_box.setEnabled(enabled)

    def _status_text(self) -> str:
        """@brief Connection and device state for the connection panel.

        @return e.g. "Conectado a /dev/ttyUSB0 @ 921600 · ESP32 adquiriendo (firmware 2.0)".
        """
        if self._acquiring:
            device = f"ESP32 adquiriendo (firmware {self._fw_version})"
        else:
            device = "ESP32 en espera: pulsa «Inicializar ESP32»"
        return f"Conectado a {self._port_name()} @ {self._baud} · {device}"

    # --------------------------- outgoing commands ---------------------------
    # Payloads follow README.md "Protocolo"; update both sides together.

    def _send_init(self) -> None:
        """@brief Send INIT. The panels are reset only when the matching ACK arrives."""
        self.worker.send(protocol.CMD_INIT)

    def _send_config(self, cfg: Config) -> None:
        """@brief Send the whole configuration as one CFG; it counts only once confirmed.

        @param cfg  Configuration from the panel (or one being restored).
        """
        if self.worker.send(cfg.payload()):
            self._cfg_pending = True
            self.config_panel.set_pending()

    def _send_manual(self, payload: str) -> None:
        """@brief Send a payload typed in the manual command box, as is.

        BAUD is refused here: the link speed must go through the selector, which runs the
        ordered renegotiation; a bare BAUD would leave the two ends at different speeds.

        @param payload  Payload without '$' or checksum, e.g. "CFG,sampling_hz=3,...".
        """
        if not payload.isascii():
            self.statusBar().showMessage("El comando solo puede tener caracteres ASCII", 5000)
            return
        kind = payload.split(",")[0]
        if kind == protocol.CMD_BAUD:
            self.statusBar().showMessage("Para cambiar la velocidad usa el selector de baud rate",
                                         5000)
            return
        if self.worker.send(payload):
            self.statusBar().showMessage(f"Enviado: {payload}", 3000)
            if kind == protocol.CMD_CFG:
                self._cfg_pending = True
                self.config_panel.set_pending()

    # --------------------------- baud renegotiation --------------------------
    # Carried over from Tarea 1. Both ends cannot switch at the same instant, so they switch
    # in order: the firmware answers at the old speed and only then changes its divisor, and
    # the PC changes its own when that answer arrives. Every step is driven from _on_frame():
    #
    #   selector ──▶ _request_baud_change ──▶ $BAUD,<n> ─────────────────────────▶ ESP32
    #   $ACK,BAUD,<n> ──▶ worker.request_baud ──▶ baud_changed ──▶ $INIT ────────▶ ESP32
    #   $ACK,INIT ──▶ _finish_baud_change (also what tells the firmware to keep the rate)
    #
    # If any step is missed the firmware falls back after LINK_BAUD_REVERT_MS and
    # _on_baud_timeout() brings the PC back to the same speed. New in T2: the INIT resets the
    # firmware's configuration, so the one in force is restored after it (_restore_cfg).

    def _request_baud_change(self, baud: int) -> None:
        """@brief Ask the firmware to move the link to @p baud.

        The selector is locked until the outcome is known, so a second request cannot be
        issued while the two ends are mid-switch.

        @param baud  Rate chosen in the connection panel; one of its BAUD_RATES.
        """
        if baud == self._baud:
            return
        if self._acquiring:
            self._restore_cfg = self._confirmed
        self._baud_pending = baud
        self.connection.set_busy(True)
        self.connection.set_connected(True, f"Cambiando a {baud} baud…")
        if not self.worker.send(f"{protocol.CMD_BAUD},{baud}"):
            self._abort_baud_change("No se pudo enviar el cambio de velocidad")
            return
        self._baud_timer.start(BAUD_NEGOTIATION_MS)

    def _on_baud_changed(self, _baud: int) -> None:
        """@brief The port changed speed: say something at the new speed, namely INIT.

        The firmware treats any valid frame as confirmation and keeps the speed it switched
        to; INIT is the one to send because a BAUD command also stops the acquisition, which
        INIT restarts. This runs for the fallback switch of _abort_baud_change() too, where
        it is equally what the link needs: the firmware has reverted and is waiting to be
        started again.

        @param _baud  Speed the port is now running at (unused; the state is in _baud).
        """
        self.worker.send(protocol.CMD_INIT)

    def _finish_baud_change(self) -> None:
        """@brief A frame came back at the new speed: the renegotiation is complete."""
        self._baud = self._baud_pending or self._baud
        self._baud_pending = None
        self._baud_timer.stop()
        self.connection.set_busy(False)
        self.connection.set_connected(True, self._status_text())

    def _abort_baud_change(self, why: str) -> None:
        """@brief Give up on the renegotiation and put both ends back on the old speed.

        The firmware reverts on its own once no frame reaches it (LINK_BAUD_REVERT_MS), so
        restoring the PC side is enough to make the link usable again. If the PC had already
        switched, putting it back also triggers _on_baud_changed() and therefore an INIT,
        which restarts the acquisition the BAUD command stopped; if it never switched (a rate
        the firmware refused outright) nothing was stopped in the first place.

        @param why  Reason shown in the status bar.
        """
        self._baud_timer.stop()
        self._baud_pending = None
        self.worker.request_baud(self._baud)
        self.connection.set_baud(self._baud)
        self.connection.set_busy(False)
        self.connection.set_connected(True, self._status_text())
        self.statusBar().showMessage(
            f"{why}: se volvió a {self._baud} baud. "
            "Si no llegan datos, pulsa «Inicializar ESP32».", 8000)

    def _on_baud_timeout(self) -> None:
        """@brief Nothing came back at the new speed within BAUD_NEGOTIATION_MS."""
        self._abort_baud_change("El ESP32 no respondió al cambio de velocidad")

    def _port_name(self) -> str:
        """@brief Device name of the open port, for status messages.

        Read from the panel rather than from the worker, which does not expose it and whose
        port selector is locked while connected, so the two cannot disagree.

        @return The device name, or "" if nothing is selected.
        """
        return self.connection.port_combo.currentData() or ""

    # --------------------------- incoming frames ----------------------------

    def _on_frame(self, fields: List[str]) -> None:
        """@brief Route one valid frame by its type and update the counters.

        - SMP: readings, plots, and the "sin datos" watchdog.
        - PEAK: peak history and a marker on the temperature plot.
        - ACK: INIT, CFG and BAUD each have a handler (see _on_ack()).
        - ERR: status bar, rejection of a pending CFG, abort of a pending renegotiation.

        A frame with a valid checksum but malformed fields, or of an unknown type, counts as
        rejected instead of valid, so the two counters stay mutually exclusive (T1 rule). The
        decoding happens before anything is updated, so such a frame changes nothing.

        @param fields  Payload fields from SerialWorker.frame_received; fields[0] is the type.
        """
        kind = fields[0]
        try:
            if kind == protocol.MSG_SMP:
                self._on_sample(messages.parse_sample(fields))
            elif kind == protocol.MSG_PEAK:
                self._on_peak(messages.parse_peak(fields))
            elif kind == protocol.MSG_ACK:
                self._on_ack(fields)
            elif kind == protocol.MSG_ERR:
                self._on_err(fields)
            else:
                raise ValueError(f"tipo de mensaje desconocido: {kind}")
        except (ValueError, KeyError, IndexError):
            self._frames_bad += 1
        else:
            self._frames_ok += 1
        self._update_counters()

    def _on_sample(self, sample: messages.Sample) -> None:
        """@brief One acquisition: show it, plot what it carries, re-arm the watchdog.

        An invalid reading (error code) is shown as such and plots nothing.

        @param sample  Decoded SMP frame.
        """
        self.readings.update_sample(sample)
        if sample.error is None:
            for var, value in sample.values.items():
                self.plots.push(var, sample.t_ms, value)
            if sample.avg_c is not None:
                self.plots.push("avg", sample.t_ms, sample.avg_c)
        self._data_timer.start(int(NO_DATA_PERIODS * 1000 / self._confirmed.sampling_hz))

    def _on_peak(self, peak: messages.Peak) -> None:
        """@brief A peak detected by the ESP32: add it to the history and mark it on the plot.

        @param peak  Decoded PEAK frame.
        """
        self.peaks.add_peak(peak)
        self.plots.add_peak(peak.t_ms, peak.peak_c)
        self.statusBar().showMessage(
            f"Pico detectado por el ESP32: {peak.peak_c:.2f} °C (θ = {peak.threshold_c:.1f} °C)",
            5000)

    def _on_ack(self, fields: List[str]) -> None:
        """@brief A command was accepted.

        - ACK,BAUD,<n> is the cue to move the PC side of the link (renegotiation above).
        - ACK,INIT,<version>: the firmware restored its defaults and started acquiring.
        - ACK,CFG,<config>: the configuration in force, as the firmware echoes it.

        @param fields  The frame's fields; fields[0] is "ACK".
        @throws ValueError / IndexError for a malformed ACK (counted as rejected).
        """
        what = fields[1] if len(fields) > 1 else ""
        if what == protocol.CMD_BAUD:
            try:
                baud = int(fields[2])
            except (ValueError, IndexError):
                self._abort_baud_change("Respuesta de velocidad ilegible")
                raise
            self._acquiring = False       # BAUD stops it; the INIT that follows restarts it
            self.worker.request_baud(baud)
        elif what == protocol.CMD_INIT:
            self._on_init_ack(fields[2] if len(fields) > 2 else "?")
        elif what == protocol.CMD_CFG:
            self._on_cfg_confirmed(messages.parse_config(fields[2:]))
        self.statusBar().showMessage(f"ESP32: OK {what}", 3000)

    def _on_init_ack(self, version: str) -> None:
        """@brief The firmware restored its defaults and (re)started: the GUI follows.

        Clears the data, shows the defaults as both the controls and the confirmed
        configuration, completes a pending renegotiation, and re-sends the configuration of
        an interrupted session if there is one (_restore_cfg).

        @param version  Firmware version from the ACK.
        """
        self._acquiring = True
        self._fw_version = version
        self.readings.clear()
        self.plots.clear()
        self.config_panel.set_controls(Config())
        self._on_cfg_confirmed(Config())
        if self._baud_pending is not None:
            self._finish_baud_change()      # a frame at the new speed: it works
        self.connection.set_connected(True, self._status_text())
        if self._restore_cfg is not None:
            cfg, self._restore_cfg = self._restore_cfg, None
            if cfg != Config():
                self.config_panel.set_controls(cfg)
                self._send_config(cfg)
            self.statusBar().showMessage("Sesión restablecida: se reenvió la configuración", 5000)

    def _on_cfg_confirmed(self, cfg: Config) -> None:
        """@brief @p cfg is in force on the ESP32: every panel follows it.

        @param cfg  Configuration from ACK,CFG, or the defaults after ACK,INIT.
        """
        self._cfg_pending = False
        self._confirmed = cfg
        self.config_panel.set_confirmed(cfg)
        for var in "THP":
            self.plots.set_transmitted(var, var in cfg.variables)
        self.plots.set_threshold(cfg.peak_enabled, cfg.threshold_c)
        self.peaks.set_threshold(cfg.peak_enabled, cfg.threshold_c)
        self.readings.set_avg_config(cfg.avg_enabled, cfg.window_s)

    def _on_err(self, fields: List[str]) -> None:
        """@brief A command was rejected: show why; nothing changed on the ESP32.

        @param fields  The frame's fields; fields[0] is "ERR", e.g. ["ERR", "BADARG", "window_s"].
        """
        reason = ",".join(fields[1:])
        self.statusBar().showMessage(f"ESP32: ERROR {reason}", 5000)
        if self._cfg_pending:
            self._cfg_pending = False
            self.config_panel.set_rejected(reason)
        if self._baud_pending is not None:
            self._abort_baud_change("El ESP32 rechazó la velocidad")

    def _on_bad_line(self, _line: str) -> None:
        """@brief Count a line that was not a valid frame (boot output, logs, corruption).

        @param _line  The rejected line; currently unused beyond counting.
        """
        self._frames_bad += 1
        self._update_counters()

    def _update_counters(self) -> None:
        """@brief Refresh the "tramas OK / rechazadas" label in the status bar."""
        self._counter_label.setText(
            f"tramas OK: {self._frames_ok}   rechazadas: {self._frames_bad}")

    # ----------------------------- close ----------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """@brief Close the serial port before the window goes away.

        @param event  QCloseEvent passed by Qt.
        """
        self._want_connected = False
        self._reconnect_timer.stop()
        self.worker.close()
        super().closeEvent(event)
