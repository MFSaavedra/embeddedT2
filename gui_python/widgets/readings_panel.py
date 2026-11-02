"""@file readings_panel.py
@brief Latest T / H / P values with units, plus packet timing (T2 spec 4, "Visualización").

Adapted from Tarea 1's env_panel.py. A variable missing from a packet is shown as
"no transmitida" instead of keeping its last value, so a deselected variable is recognisable
at a glance (spec 4). The timing line shows the ESP32 sequence number and timestamp and the
Δt between consecutive packets, which is the evidence for spec test 6.3 (1 Hz -> 5 Hz).

TODO(PY4): "sin datos" after ~2.5 sampling periods without a packet, and an "inválida" state
for the error form of SMP (spec 4, "Resultados").
"""
from __future__ import annotations

import time
from typing import Dict, Mapping, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGridLayout, QGroupBox, QLabel

## (key, title, unit, number format) per variable, in display order.
VARIABLES = (
    ("T", "Temperatura", "°C", "{:.2f}"),
    ("H", "Humedad", "%HR", "{:.1f}"),
    ("P", "Presión", "hPa", "{:.2f}"),
)
## Text shown for a variable that the current packet does not carry.
NOT_SENT = "no transmitida"
## Style of a value label showing a measurement.
VALUE_STYLE = "font-size: 24px; font-weight: bold;"
## Style of a value label showing NOT_SENT (smaller, so the text fits the column).
NOT_SENT_STYLE = "font-size: 14px; font-style: italic;"


class ReadingsPanel(QGroupBox):
    """@brief Three large numeric indicators plus a line with seq / ESP32 time / Δt."""

    def __init__(self, parent=None):
        """@brief Build the labels in their empty ("--") state.

        @param parent  Optional QWidget parent.
        """
        super().__init__("Lecturas BME688", parent)
        ## Value label per variable key ("T", "H", "P").
        self.value_labels: Dict[str, QLabel] = {}
        ## seq, ESP32 time, Δt between packets and local arrival time.
        self.timing_label = QLabel()
        ## ESP32 timestamp of the previous packet, for Δt; None until one arrives.
        self._last_t_ms: Optional[int] = None

        grid = QGridLayout(self)
        for col, (key, title, unit, _fmt) in enumerate(VARIABLES):
            grid.addWidget(QLabel(f"{title} [{unit}]"), 0, col, Qt.AlignCenter)
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            grid.addWidget(label, 1, col)
            self.value_labels[key] = label
        grid.addWidget(self.timing_label, 2, 0, 1, len(VARIABLES), Qt.AlignCenter)
        self.clear()

    def update_sample(self, seq: int, t_ms: int, values: Mapping[str, float]) -> None:
        """@brief Show one packet: its values, and "no transmitida" for the rest.

        @param seq     Sequence number sent by the ESP32.
        @param t_ms    ESP32 timestamp of the measurement, ms.
        @param values  Measured values keyed "T" / "H" / "P"; absent keys were not transmitted.
        """
        for key, _title, unit, fmt in VARIABLES:
            label = self.value_labels[key]
            if key in values:
                label.setText(f"{fmt.format(values[key])} {unit}")
                label.setStyleSheet(VALUE_STYLE)
                label.setEnabled(True)
            else:
                label.setText(NOT_SENT)
                label.setStyleSheet(NOT_SENT_STYLE)
                label.setEnabled(False)
        dt = "" if self._last_t_ms is None else f" · Δt {t_ms - self._last_t_ms} ms"
        self._last_t_ms = t_ms
        self.timing_label.setText(
            f"seq {seq} · t ESP32 {t_ms / 1000:.3f} s{dt} · {time.strftime('%H:%M:%S')}")

    def clear(self) -> None:
        """@brief Back to the empty state (on connect / Inicializar)."""
        for label in self.value_labels.values():
            label.setText("--")
            label.setStyleSheet(VALUE_STYLE)
            label.setEnabled(True)
        self._last_t_ms = None
        self.timing_label.setText("sin datos")
