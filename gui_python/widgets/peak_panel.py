"""@file peak_panel.py
@brief History of the temperature peaks detected by the ESP32, and the threshold in force
(T2 spec 3.2: "La GUI debe mostrar un historial de eventos de pico y el valor actual del
umbral").

Each PEAK frame becomes one row, newest first: the ESP32 time of the peak ("t [s]"), the PC
time it arrived, the peak value and the threshold the ESP32 applied. The history survives INIT and
reconnections (the PC time column keeps the rows unambiguous); Limpiar empties it.
"""
from __future__ import annotations

import time

from PyQt5.QtWidgets import (QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout)

from messages import Peak

## Column titles of the history table.
COLUMNS = ("t [s]", "Hora PC", "Pico [°C]", "θ [°C]")
## Oldest rows are dropped beyond this many.
MAX_ROWS = 200


class PeakPanel(QGroupBox):
    """@brief Current threshold plus a table of every peak event received."""

    def __init__(self, parent=None):
        """@brief Build an empty history.

        @param parent  Optional QWidget parent.
        """
        super().__init__("Eventos de pico de temperatura (ESP32)", parent)
        ## Threshold and on/off state confirmed by the ESP32.
        self.threshold_label = QLabel()
        self.threshold_label.setWordWrap(True)
        ## Peak history, newest first.
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeaderItem(0).setToolTip("Instante del pico en el reloj del ESP32")
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        ## Empties the history.
        self.clear_btn = QPushButton("Limpiar")
        self.clear_btn.clicked.connect(lambda: self.table.setRowCount(0))

        top = QHBoxLayout()
        top.addWidget(self.threshold_label, 1)
        top.addWidget(self.clear_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table)
        self.set_threshold(False, 28.0)

    def set_threshold(self, enabled: bool, threshold_c: float) -> None:
        """@brief Show the peak settings the ESP32 confirmed.

        @param enabled      Whether the ESP32 is detecting peaks.
        @param threshold_c  Threshold θ in force, °C.
        """
        state = "detección activada" if enabled else "detección desactivada"
        self.threshold_label.setText(f"Umbral θ actual: {threshold_c:.1f} °C · {state}")

    def add_peak(self, peak: Peak) -> None:
        """@brief Add one PEAK event at the top of the history.

        @param peak  Decoded PEAK frame.
        """
        self.table.insertRow(0)
        cells = (f"{peak.t_ms / 1000:.3f}", time.strftime("%H:%M:%S"),
                 f"{peak.peak_c:.2f}", f"{peak.threshold_c:.1f}")
        for col, text in enumerate(cells):
            self.table.setItem(0, col, QTableWidgetItem(text))
        if self.table.rowCount() > MAX_ROWS:
            self.table.removeRow(MAX_ROWS)
