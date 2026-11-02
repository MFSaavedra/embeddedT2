"""@file readings_panel.py
@brief Latest T / H / P values with units, the ESP32's moving average, and the state of the
data stream (T2 spec 4, "Visualización" and "Resultados").

Adapted from Tarea 1's env_panel.py. What it shows:
- the three values; a variable missing from a packet reads "no transmitida" instead of keeping
  its last value, so a deselected variable is recognisable at a glance;
- the moving average computed by the ESP32 (temp_avg_c) with its N and whether the window is
  complete, and next to it a recomputation from the temperatures received, labelled as
  validation only (spec 4: the PC may recompute "solo para validación");
- the stream state: valid reading, "lectura inválida" (an SMP with an error code), or
  "sin datos" (MainWindow's watchdog);
- seq, ESP32 time, Δt between packets and frames lost (gaps in seq): the evidence for spec
  test 6.3 (1 Hz -> 5 Hz).
"""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGridLayout, QGroupBox, QLabel

from messages import Sample

## (key, title, unit, number format) per variable, in display order.
VARIABLES = (
    ("T", "Temperatura", "°C", "{:.2f}"),
    ("H", "Humedad", "%HR", "{:.2f}"),
    ("P", "Presión", "hPa", "{:.2f}"),
)
## Text shown for a variable that the current packet does not carry.
NOT_SENT = "no transmitida"
## Style of a value label showing a measurement.
VALUE_STYLE = "font-size: 24px; font-weight: bold;"
## Style of a value label showing NOT_SENT (smaller, so the text fits the column).
NOT_SENT_STYLE = "font-size: 14px; font-style: italic;"
## Style of the state line while readings are valid.
OK_STYLE = "color: #1b7f3b; font-weight: bold;"
## Style of the state line for an invalid reading or a silent link.
BAD_STYLE = "color: #c62828; font-weight: bold;"
## Seconds of received temperatures kept for the PC-side check (longest W plus margin).
HISTORY_S = 70


class ReadingsPanel(QGroupBox):
    """@brief Three large numeric indicators, the average, the stream state and the timing."""

    def __init__(self, parent=None):
        """@brief Build the labels in their empty state.

        @param parent  Optional QWidget parent.
        """
        super().__init__("Lecturas BME688", parent)
        ## Value label per variable key ("T", "H", "P").
        self.value_labels: Dict[str, QLabel] = {}
        ## Moving average received from the ESP32.
        self.avg_label = QLabel()
        ## The same average recomputed on the PC, for validation only.
        self.check_label = QLabel()
        ## Valid / invalid reading / no data.
        self.state_label = QLabel()
        ## seq, ESP32 time, Δt between packets, lost frames and local arrival time.
        self.timing_label = QLabel()
        ## Whether the ESP32 is sending the average (confirmed configuration).
        self._avg_enabled = False
        ## Average window W in force on the ESP32, s.
        self._window_s = 10
        ## ESP32 timestamp of the previous packet, for Δt; None until one arrives.
        self._last_t_ms: Optional[int] = None
        ## Sequence number of the previous packet; None until one arrives.
        self._last_seq: Optional[int] = None
        ## Frames missing from the sequence since the last clear().
        self._lost = 0
        ## (t_ms, °C) of the temperatures received, for the PC-side check of the average.
        self._t_history: Deque[Tuple[int, float]] = deque()

        grid = QGridLayout(self)
        for col, (key, title, unit, _fmt) in enumerate(VARIABLES):
            grid.addWidget(QLabel(f"{title} [{unit}]"), 0, col, Qt.AlignCenter)
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            grid.addWidget(label, 1, col)
            self.value_labels[key] = label
        span = len(VARIABLES)
        for label in (self.avg_label, self.check_label, self.state_label, self.timing_label):
            label.setWordWrap(True)
        grid.addWidget(self.avg_label, 2, 0, 1, span)
        grid.addWidget(self.check_label, 3, 0, 1, span)
        grid.addWidget(self.state_label, 4, 0, 1, span)
        grid.addWidget(self.timing_label, 5, 0, 1, span)
        self.clear()

    # --------------------------------- inputs ---------------------------------

    def set_avg_config(self, enabled: bool, window_s: int) -> None:
        """@brief Follow the average settings the ESP32 confirmed.

        @param enabled   Whether the ESP32 computes and sends the average.
        @param window_s  Window W in force, s.
        """
        self._avg_enabled = enabled
        self._window_s = window_s
        if not enabled:
            self.avg_label.setText("Promedio T (ESP32): desactivado")
            self.check_label.setText("")

    def update_sample(self, sample: Sample) -> None:
        """@brief Show one SMP: its values (or that it is invalid), the average and the timing.

        @param sample  Decoded SMP frame.
        """
        if sample.error is not None:
            for label in self.value_labels.values():
                self._show(label, "inválida", NOT_SENT_STYLE, False)
            self.state_label.setText(f"LECTURA INVÁLIDA en el ESP32 ({sample.error}): "
                                     "no se reciben valores")
            self.state_label.setStyleSheet(BAD_STYLE)
        else:
            for key, _title, unit, fmt in VARIABLES:
                if key in sample.values:
                    self._show(self.value_labels[key], f"{fmt.format(sample.values[key])} {unit}",
                               VALUE_STYLE, True)
                else:
                    self._show(self.value_labels[key], NOT_SENT, NOT_SENT_STYLE, False)
            self.state_label.setText("Lectura válida")
            self.state_label.setStyleSheet(OK_STYLE)
            if "T" in sample.values:
                self._remember_temperature(sample.t_ms, sample.values["T"])
            if sample.avg_c is not None:
                self._show_average(sample)
        self._show_timing(sample)

    def set_no_data(self) -> None:
        """@brief Nothing has arrived for a while (MainWindow's watchdog) or the link is down."""
        self.state_label.setText(f"SIN DATOS desde las {time.strftime('%H:%M:%S')}")
        self.state_label.setStyleSheet(BAD_STYLE)
        for label in self.value_labels.values():
            label.setEnabled(False)

    def clear(self) -> None:
        """@brief Back to the empty state (on connect / Inicializar)."""
        for label in self.value_labels.values():
            self._show(label, "--", VALUE_STYLE, True)
        self._last_t_ms = None
        self._last_seq = None
        self._lost = 0
        self._t_history.clear()
        self.avg_label.setText("Promedio T (ESP32): " +
                               ("--" if self._avg_enabled else "desactivado"))
        self.check_label.setText("")
        self.state_label.setText("sin datos")
        self.state_label.setStyleSheet("")
        self.timing_label.setText("")

    # -------------------------------- helpers ---------------------------------

    @staticmethod
    def _show(label: QLabel, text: str, style: str, enabled: bool) -> None:
        """@brief Set a value label's text, style and enabled state at once.

        @param label    The label.
        @param text     Text to show.
        @param style    Style sheet.
        @param enabled  False greys it out.
        """
        label.setText(text)
        label.setStyleSheet(style)
        label.setEnabled(enabled)

    def _remember_temperature(self, t_ms: int, temp_c: float) -> None:
        """@brief Keep a received temperature for the PC-side check (last HISTORY_S seconds).

        @param t_ms    ESP32 time of the reading.
        @param temp_c  Temperature, °C.
        """
        self._t_history.append((t_ms, temp_c))
        while self._t_history and self._t_history[0][0] <= t_ms - HISTORY_S * 1000:
            self._t_history.popleft()

    def _show_average(self, sample: Sample) -> None:
        """@brief Show the ESP32's average and, when possible, the PC's recomputation.

        The PC applies the same definition as the firmware, the mean of the temperatures with
        t - W < t_i <= t, to the temperatures it received. It can only do so while T is
        transmitted, and it matches the ESP32 when it received the same samples (equal N).

        @param sample  An SMP carrying temp_avg_c.
        """
        complete = "ventana completa" if sample.avg_complete else "VENTANA INCOMPLETA"
        self.avg_label.setText(f"Promedio T (ESP32): {sample.avg_c:.2f} °C · "
                               f"W = {self._window_s} s · N = {sample.avg_n} · {complete}")
        if "T" not in sample.values:
            self.check_label.setText("Validación PC: no disponible (T no se transmite)")
            return
        start = sample.t_ms - self._window_s * 1000
        window = [v for t, v in self._t_history if start < t <= sample.t_ms]
        mean = sum(window) / len(window)
        diff = round(sample.avg_c - mean, 2) + 0.0      # + 0.0 turns -0.0 into 0.0
        self.check_label.setText(f"Validación PC (solo verificación): {mean:.2f} °C · "
                                 f"N = {len(window)} · diferencia {diff:+.2f} °C")

    def _show_timing(self, sample: Sample) -> None:
        """@brief Update seq / ESP32 time / Δt / lost frames from one SMP.

        @param sample  Decoded SMP frame.
        """
        if self._last_seq is not None and sample.seq > self._last_seq + 1:
            self._lost += sample.seq - self._last_seq - 1
        dt = "" if self._last_t_ms is None else f" · Δt {sample.t_ms - self._last_t_ms} ms"
        self._last_seq = sample.seq
        self._last_t_ms = sample.t_ms
        self.timing_label.setText(
            f"seq {sample.seq} · t ESP32 {sample.t_ms / 1000:.3f} s{dt} · "
            f"perdidos {self._lost} · {time.strftime('%H:%M:%S')}")
