"""@file main_window.py
@brief Main window: wires the panels, the plots and the serial worker together.

Data flow (carried over from Tarea 1; the T2 panels plug into the same two paths):

    panels ──(Qt signals)──▶ MainWindow._send_*()  ──▶ SerialWorker.send(payload)
    SerialWorker.frame_received ──▶ MainWindow._on_frame(fields) ──▶ readings / plots / status bar
    SerialWorker.baud_changed   ──▶ MainWindow._on_baud_changed  ──▶ SerialWorker.send("INIT")

Nothing here touches pyserial directly and nothing in serial_worker.py touches widgets: the
worker is told *when* to change the link speed but never learns what a BAUD frame is.

TODO(PY2): route SMP / PEAK once P1 fixes their fields (README "Protocolo").
TODO(PY3): acquisition + processing panels building one atomic CFG, and a display of the
configuration the ACK confirmed (spec 4: "mostrar la configuración que el ESP32 confirmó").
"""
from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QVBoxLayout, QWidget

import protocol
from serial_worker import SerialWorker, available_ports
from widgets.connection_panel import ConnectionPanel
from widgets.readings_panel import ReadingsPanel
from widgets.sensor_plots import SensorPlots

## How long to wait for a baud renegotiation to complete before giving up, ms. Must exceed
## LINK_BAUD_REVERT_MS in app_config.h so the firmware has already fallen back by then and
## both ends land on the same speed.
BAUD_NEGOTIATION_MS = 8000


class MainWindow(QMainWindow):
    """@brief Top-level window: control column on the left, the T/H/P plots on the right.

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
        ## Latest T / H / P values and packet timing (spec 4, "Visualización").
        self.readings = ReadingsPanel()
        ## T / H / P history plots (spec 4, "Visualización").
        self.plots = SensorPlots()

        # ---- layout: control column on the left, plots on the right ----
        left = QVBoxLayout()
        left.addWidget(self.connection)
        # TODO(PY3): acquisition panel (rate, T/H/P selection) and processing panel (average +
        #            W, peaks + threshold) here, plus the configuration the ESP32 confirmed.
        left.addWidget(self.readings)
        # TODO(PY6): peak event history (time, value, threshold) here.
        left.addStretch(1)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(560)

        root = QHBoxLayout()
        root.addWidget(left_widget)
        root.addWidget(self.plots, 1)
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
        ## Status-bar label showing both counters.
        self._counter_label = QLabel()
        self.statusBar().addPermanentWidget(self._counter_label)
        self._update_counters()

        # ---- wiring (hidden from Doxygen, which would read each self._callback as an attribute) ----
        # @cond
        self.connection.refresh_requested.connect(self._refresh_ports)
        self.connection.connect_requested.connect(self._connect)
        self.connection.disconnect_requested.connect(self.worker.close)
        self.connection.init_requested.connect(self._send_init)
        self.connection.baud_change_requested.connect(self._request_baud_change)
        self._baud_timer.timeout.connect(self._on_baud_timeout)

        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.error.connect(self._on_error)
        self.worker.baud_changed.connect(self._on_baud_changed)
        self.worker.frame_received.connect(self._on_frame)
        self.worker.bad_line.connect(self._on_bad_line)
        # @endcond

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
            self.connection.set_connected(False, f"Conectando a {port}… (reiniciando ESP32)")

    def _on_connected(self, port: str, baud: int) -> None:
        """@brief Port open and board rebooted: enable the controls and clear stale data.

        The port was opened at the board's boot speed. If the user asked for a different one
        - before connecting, or during an earlier session - the link is renegotiated now, so
        the selector means the same thing whenever it is touched.

        @param port  Device name that was opened.
        @param baud  Baud rate the port was opened at.
        """
        self._baud = baud
        self.connection.set_connected(True, f"Conectado a {port} @ {baud}")
        self.readings.clear()
        self.plots.clear()
        target = self.connection.target_baud()
        if target != baud:
            self._request_baud_change(target)

    def _on_disconnected(self) -> None:
        """@brief Port closed (by the user or by an error): disable the controls.

        The selector keeps whatever the user chose: it is a preference, not the speed the
        port is opened at, so the next connect opens at the boot speed and renegotiates back
        to it by itself.

        TODO(PY1): an unexpected disconnect (cable pulled) should be told apart from the user's
        Desconectar and offer, or attempt, a reconnect (spec 6.7).
        """
        self._baud_timer.stop()
        self._baud_pending = None
        self._baud = 0
        self.connection.set_busy(False)
        self.connection.set_connected(False)

    def _on_error(self, message: str) -> None:
        """@brief Show a worker error in the status bar for 5 s.

        @param message  Human-readable text from SerialWorker.error.
        """
        self.statusBar().showMessage(message, 5000)

    # --------------------------- outgoing commands ---------------------------
    # Payloads follow README.md "Protocolo"; update both sides together.

    def _send_init(self) -> None:
        """@brief Send INIT. The panels are reset only when the matching ACK arrives."""
        self.worker.send(protocol.CMD_INIT)

    # --------------------------- baud renegotiation --------------------------
    # Carried over from Tarea 1 unchanged. Both ends cannot switch at the same instant, so
    # they switch in order: the firmware answers at the old speed and only then changes its
    # divisor, and the PC changes its own when that answer arrives. Every step is driven from
    # _on_frame():
    #
    #   selector ──▶ _request_baud_change ──▶ $BAUD,<n> ─────────────────────────▶ ESP32
    #   $ACK,BAUD,<n> ──▶ worker.request_baud ──▶ baud_changed ──▶ $INIT ────────▶ ESP32
    #   $ACK,INIT ──▶ _finish_baud_change (also what tells the firmware to keep the rate)
    #
    # If any step is missed the firmware falls back after LINK_BAUD_REVERT_MS and
    # _on_baud_timeout() brings the PC back to the same speed.

    def _request_baud_change(self, baud: int) -> None:
        """@brief Ask the firmware to move the link to @p baud.

        The selector is locked until the outcome is known, so a second request cannot be
        issued while the two ends are mid-switch.

        @param baud  Rate chosen in the connection panel; one of its BAUD_RATES.
        """
        if baud == self._baud:
            return
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
        self.connection.set_connected(True, f"Conectado a {self._port_name()} @ {self._baud}")

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
        self.connection.set_connected(True, f"Conectado a {self._port_name()} @ {self._baud}")
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

        - ACK: shown in the status bar; ACK,INIT also clears the readings and plots, since the
          firmware has just restored its defaults, and ACK,BAUD is the cue to move the PC side
          of the link to the new speed (see the renegotiation section above).
        - ERR: shown in the status bar; it also aborts a renegotiation in progress, which is
          how a rate the firmware refuses outright is handled without waiting.
        - SMP / PEAK: TODO(PY2), see the module docstring.

        A frame with a valid checksum but malformed fields must be counted as rejected
        instead of valid, so the two counters stay mutually exclusive (T1 rule; keep it when
        adding SMP / PEAK).

        @param fields  Payload fields from SerialWorker.frame_received; fields[0] is the type.
        """
        self._frames_ok += 1
        kind = fields[0]
        if kind == protocol.MSG_ACK:
            self.statusBar().showMessage("ESP32: OK " + ",".join(fields[1:]), 3000)
            if len(fields) > 1 and fields[1] == protocol.CMD_INIT:
                self.readings.clear()
                self.plots.clear()
                # TODO(PY3): reset the acquisition / processing panels to the firmware defaults.
                if self._baud_pending is not None:
                    self._finish_baud_change()   # a frame at the new speed: it works
            elif len(fields) > 1 and fields[1] == protocol.CMD_BAUD:
                try:
                    self.worker.request_baud(int(fields[2]))
                except (ValueError, IndexError):
                    self._frames_ok -= 1
                    self._frames_bad += 1
                    self._abort_baud_change("Respuesta de velocidad ilegible")
        elif kind == protocol.MSG_ERR:
            self.statusBar().showMessage("ESP32: ERROR " + ",".join(fields[1:]), 5000)
            if self._baud_pending is not None:
                self._abort_baud_change("El ESP32 rechazó la velocidad")
        self._update_counters()

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
        self.worker.close()
        super().closeEvent(event)
