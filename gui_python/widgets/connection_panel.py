"""@file connection_panel.py
@brief Connection panel (T2 spec 4, "Conexión"): port + baud selection, Conectar/Desconectar, Inicializar.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                             QPushButton)

## Baud rates offered in the combo box (the higher ones are needed for 3 x 1000 Hz).
## Must match uart_link_valid_baud() in esp32_firmware/main/uart_link.c, which decides
## which rates a BAUD command may switch the link to.
BAUD_RATES = [115200, 230400, 460800, 921600]
## Speed the port is always opened at: the board boots into its compile-time LINK_BAUD and
## the GUI resets it on every connect, so no other rate can work for the first byte. Keep in
## sync with LINK_BAUD in esp32_firmware/main/app_config.h.
DEFAULT_BAUD = 921600


class ConnectionPanel(QGroupBox):
    """@brief Port / baud selectors plus the Conectar and Inicializar ESP32 buttons.

    The panel only emits requests; MainWindow performs them and reports back through
    set_ports() and set_connected().

    The baud selector means one thing in both states: the speed the *link* should run at.
    It is never the speed the port is opened at - that is always DEFAULT_BAUD, because the
    board boots into its compile-time rate. Picking another rate while connected
    renegotiates (baud_change_requested); picking one while disconnected is remembered and
    MainWindow renegotiates as soon as the connection is up.
    """

    ## User pressed Conectar: (port, baud).
    connect_requested = pyqtSignal(str, int)
    ## User pressed Desconectar.
    disconnect_requested = pyqtSignal()
    ## User pressed Inicializar ESP32.
    init_requested = pyqtSignal()
    ## User pressed the refresh button next to the port list.
    refresh_requested = pyqtSignal()
    ## User picked another baud rate while connected: renegotiate the link now.
    baud_change_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        """@brief Build the widgets in their disconnected state.

        @param parent  Optional QWidget parent.
        """
        super().__init__("Conexión serial", parent)
        ## Mirrors the last set_connected() call; decides what the connect button does.
        self._connected = False
        ## True while a renegotiation is in flight (set_busy()); locks what must not be
        ## touched mid-switch.
        self._busy = False

        ## Serial port selector, filled by set_ports().
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(140)
        ## Rescans the ports (emits refresh_requested).
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setFixedWidth(32)
        self.refresh_btn.setToolTip("Buscar puertos")

        ## Baud rate selector; item data holds the integer value.
        self.baud_combo = QComboBox()
        for baud in BAUD_RATES:
            self.baud_combo.addItem(str(baud), baud)
        self.baud_combo.setCurrentText(str(DEFAULT_BAUD))

        ## Toggles between Conectar and Desconectar depending on the state.
        self.connect_btn = QPushButton("Conectar")
        ## Sends INIT; only enabled while connected.
        self.init_btn = QPushButton("Inicializar ESP32")
        ## One-line connection status.
        self.status_label = QLabel("Desconectado")

        port_row = QHBoxLayout()
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_btn)

        grid = QGridLayout(self)
        grid.addWidget(QLabel("Puerto"), 0, 0)
        grid.addLayout(port_row, 0, 1)
        grid.addWidget(QLabel("Baud rate"), 1, 0)
        grid.addWidget(self.baud_combo, 1, 1)
        grid.addWidget(self.connect_btn, 2, 0, 1, 2)
        grid.addWidget(self.init_btn, 3, 0, 1, 2)
        grid.addWidget(self.status_label, 4, 0, 1, 2)

        self.refresh_btn.clicked.connect(self.refresh_requested)
        # Doxygen would read self._on_connect_clicked as an attribute.
        # @cond
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        self.baud_combo.currentIndexChanged.connect(self._on_baud_changed)
        # @endcond
        self.init_btn.clicked.connect(self.init_requested)
        self.set_connected(False)

    def set_ports(self, ports: List[Tuple[str, str]]) -> None:
        """@brief Repopulate the port list, keeping the current choice if it still exists.

        The combo shows the label; the device name travels as item data so that
        connect_requested carries exactly what pyserial must open. The first entry is
        preselected, which is the first USB adapter when available_ports() found one.

        @param ports  (device, label) pairs in display order, from
                      serial_worker.available_ports().
        """
        current = self.port_combo.currentData()
        self.port_combo.clear()
        for device, label in ports:
            self.port_combo.addItem(label, device)
        index = self.port_combo.findData(current)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)
        if not ports:
            self.status_label.setText("No se encontraron puertos")

    def set_connected(self, connected: bool, text: Optional[str] = None) -> None:
        """@brief Reflect the connection state: button labels, enabled widgets, status text.

        While connected the port and refresh controls are locked and Inicializar is enabled;
        while disconnected the opposite. What set_busy() locks stays locked either way.

        @param connected  True if a port is open.
        @param text       Status text; defaults to "Conectado" / "Desconectado".
        """
        self._connected = connected
        self._apply_enabled_state()
        self.status_label.setText(text or ("Conectado" if connected else "Desconectado"))

    def set_busy(self, busy: bool) -> None:
        """@brief Lock the controls that must not be used mid-renegotiation.

        Both the baud selector (a second switch while one is in flight) and Inicializar (an
        INIT written at the old speed while the firmware has already left it) would land in
        the middle of the changeover.

        @param busy  True between the BAUD command and its outcome.
        """
        self._busy = busy
        self._apply_enabled_state()

    def _apply_enabled_state(self) -> None:
        """@brief Single place that decides which controls are usable.

        Both the connection state and the busy flag feed into it, so neither can silently
        undo the other - set_connected() used to re-enable what a renegotiation had locked.
        """
        self.connect_btn.setText("Desconectar" if self._connected else "Conectar")
        self.connect_btn.setEnabled(not self._busy)
        self.init_btn.setEnabled(self._connected and not self._busy)
        self.baud_combo.setEnabled(not self._busy)
        for w in (self.port_combo, self.refresh_btn):
            w.setEnabled(not self._connected and not self._busy)

    def target_baud(self) -> int:
        """@brief Speed the user wants the link to run at.

        Read by MainWindow right after connecting: the port is open at DEFAULT_BAUD and is
        renegotiated to this value if it differs.

        @return The selected rate, one of BAUD_RATES.
        """
        return self.baud_combo.currentData()

    def set_baud(self, baud: int) -> None:
        """@brief Show @p baud on the selector without emitting baud_change_requested.

        Used when the link speed changes for a reason other than the user picking it, i.e.
        when a renegotiation fails and the GUI has to fall back.

        @param baud  Rate to display; ignored if it is not one of BAUD_RATES.
        """
        index = self.baud_combo.findData(baud)
        if index < 0:
            return
        self.baud_combo.blockSignals(True)
        self.baud_combo.setCurrentIndex(index)
        self.baud_combo.blockSignals(False)

    def _on_baud_changed(self, _index: int) -> None:
        """@brief Slot for the baud selector: renegotiate now, or leave it to the connect.

        While connected this is a request to change the speed of a running link, which only
        the firmware can grant. While disconnected there is nothing to renegotiate yet, so
        the value is simply left for target_baud() to be read at connect time.

        @param _index  New combo index (unused; currentData() is read instead).
        """
        if self._connected:
            self.baud_change_requested.emit(self.baud_combo.currentData())

    def _on_connect_clicked(self) -> None:
        """@brief Emit disconnect_requested or connect_requested depending on the state.

        The requested speed is always DEFAULT_BAUD; see _on_baud_changed() for what the baud
        selector does instead. Does nothing (beyond a hint in the status label) if no port is
        selected.
        """
        if self._connected:
            self.disconnect_requested.emit()
            return
        port = self.port_combo.currentData()
        if not port:
            self.status_label.setText("Selecciona un puerto")
            return
        # Always DEFAULT_BAUD, never the selector: the board has just been reset and boots
        # into its compile-time rate. A different selection is honoured by renegotiating
        # once the link is up (MainWindow._on_connected -> target_baud()).
        self.connect_requested.emit(port, DEFAULT_BAUD)
