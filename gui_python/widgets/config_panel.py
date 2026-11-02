"""@file config_panel.py
@brief ESP32 configuration panel (T2 spec 4, "Configuración de adquisición" and
"Procesamiento local"): sampling rate, transmitted variables, moving average and peak
detection, sent together as one CFG.

The controls only edit a proposal. Aplicar sends it as a single CFG, which the firmware
applies whole or not at all, and the panel shows what the ESP32 actually confirmed (its
ACK,CFG echo) separately from the controls (spec 4: "mostrar la configuración que el ESP32
confirmó"). Nothing is assumed applied until that confirmation arrives (spec 9).

Takes the place of Tarea 1's config_panel.py (per-axis accelerometer settings) and keeps its
_combo() helper.
"""
from __future__ import annotations

from typing import Dict, Sequence, Tuple

from PyQt5.QtCore import QLocale, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QPushButton)

from messages import RATES_HZ, THRESHOLD_MAX_C, THRESHOLD_MIN_C, WINDOWS_S, Config

## (letter, label) of the variable checkboxes, in display order.
VARIABLES = (("T", "Temperatura"), ("H", "Humedad"), ("P", "Presión"))
## Style of the state line while waiting for the ESP32's answer.
PENDING_STYLE = "color: #b26b00;"
## Style of the state line once the ESP32 confirmed.
CONFIRMED_STYLE = "color: #1b7f3b;"
## Style of the state line when the ESP32 rejected the configuration.
REJECTED_STYLE = "color: #c62828; font-weight: bold;"


def _combo(items: Sequence[Tuple[float, str]], default: float) -> QComboBox:
    """@brief Build a QComboBox from (value, label) pairs with @p default preselected.

    From Tarea 1's config_panel.py, unchanged except for float values (0.5 Hz).

    @param items    Sequence of (item data, display text).
    @param default  Item data to select initially; must be present in @p items.
    @return The populated combo box; currentData() yields the value.
    """
    combo = QComboBox()
    for value, label in items:
        combo.addItem(label, value)
    combo.setCurrentIndex([v for v, _ in items].index(default))
    return combo


class ConfigPanel(QGroupBox):
    """@brief Rate, T/H/P selection, average (on/off + W) and peaks (on/off + θ), plus Aplicar."""

    ## User pressed Aplicar: the Config built from the controls.
    apply_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        """@brief Build the controls showing the firmware defaults.

        @param parent  Optional QWidget parent.
        """
        super().__init__("Configuración del ESP32", parent)
        defaults = Config()
        ## Sampling rate selector (data: Hz).
        self.rate_combo = _combo([(hz, f"{hz:g} Hz") for hz in RATES_HZ], defaults.sampling_hz)
        ## One checkbox per variable ("T", "H", "P"): selected for transmission.
        self.var_checks: Dict[str, QCheckBox] = {v: QCheckBox(label) for v, label in VARIABLES}
        ## Moving average on/off.
        self.avg_check = QCheckBox("Activar")
        ## Average window W selector (data: s).
        self.window_combo = _combo([(s, f"{s} s") for s in WINDOWS_S], defaults.window_s)
        ## Peak detection on/off.
        self.peak_check = QCheckBox("Activar")
        ## Peak threshold θ, 0.1 °C steps.
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(THRESHOLD_MIN_C, THRESHOLD_MAX_C)
        self.threshold_spin.setDecimals(1)
        self.threshold_spin.setSingleStep(0.1)
        self.threshold_spin.setSuffix(" °C")
        self.threshold_spin.setLocale(QLocale.c())     # "24.6", like every other number shown
        ## Sends the whole configuration as one CFG.
        self.apply_btn = QPushButton("Aplicar configuración")
        ## Fate of the last CFG: pending, confirmed or rejected.
        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        ## The configuration the ESP32 confirmed last.
        self.confirmed_label = QLabel()
        self.confirmed_label.setWordWrap(True)
        self.confirmed_label.setStyleSheet("font-weight: bold;")

        var_row = QHBoxLayout()
        for check in self.var_checks.values():
            var_row.addWidget(check)
            # Doxygen would read self._guard_last_variable as an attribute.
            # @cond
            check.toggled.connect(self._guard_last_variable)
            # @endcond
        avg_row = QHBoxLayout()
        avg_row.addWidget(self.avg_check)
        avg_row.addWidget(QLabel("ventana W"))
        avg_row.addWidget(self.window_combo, 1)
        peak_row = QHBoxLayout()
        peak_row.addWidget(self.peak_check)
        peak_row.addWidget(QLabel("umbral θ"))
        peak_row.addWidget(self.threshold_spin, 1)

        form = QFormLayout(self)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)   # field under its label if narrow
        form.addRow("Frecuencia de muestreo", self.rate_combo)
        form.addRow("Variables a transmitir", var_row)
        form.addRow("Promedio móvil de T", avg_row)
        form.addRow("Detección de picos de T", peak_row)
        form.addRow(self.apply_btn)
        form.addRow("Estado:", self.state_label)
        form.addRow(QLabel("Configuración vigente en el ESP32:"))
        form.addRow(self.confirmed_label)

        self.apply_btn.clicked.connect(lambda: self.apply_requested.emit(self.config()))
        self.set_controls(defaults)
        self.set_confirmed(defaults)

    def config(self) -> Config:
        """@brief The configuration shown on the controls.

        @return A Config; its variables are never empty (see _guard_last_variable()).
        """
        return Config(sampling_hz=self.rate_combo.currentData(),
                      variables="".join(v for v, check in self.var_checks.items()
                                        if check.isChecked()),
                      avg_enabled=self.avg_check.isChecked(),
                      window_s=self.window_combo.currentData(),
                      peak_enabled=self.peak_check.isChecked(),
                      threshold_c=round(self.threshold_spin.value(), 1))

    def set_controls(self, cfg: Config) -> None:
        """@brief Show @p cfg on the controls (after INIT, or when a session is restored).

        @param cfg  Configuration to display.
        """
        self.rate_combo.setCurrentIndex(self.rate_combo.findData(float(cfg.sampling_hz)))
        for v, check in self.var_checks.items():
            check.setChecked(v in cfg.variables)
        self.avg_check.setChecked(cfg.avg_enabled)
        self.window_combo.setCurrentIndex(self.window_combo.findData(cfg.window_s))
        self.peak_check.setChecked(cfg.peak_enabled)
        self.threshold_spin.setValue(cfg.threshold_c)
        self._guard_last_variable()

    def set_pending(self) -> None:
        """@brief A CFG was sent: nothing is applied until the ESP32 answers."""
        self.state_label.setText("enviada, esperando la confirmación del ESP32…")
        self.state_label.setStyleSheet(PENDING_STYLE)

    def set_confirmed(self, cfg: Config) -> None:
        """@brief The ESP32 reports @p cfg in force (ACK,CFG echo, or its defaults after INIT).

        @param cfg  The configuration the ESP32 confirmed.
        """
        self.state_label.setText("confirmada por el ESP32")
        self.state_label.setStyleSheet(CONFIRMED_STYLE)
        self.confirmed_label.setText(cfg.describe())

    def set_rejected(self, reason: str) -> None:
        """@brief The ESP32 refused the last CFG; its previous configuration stays in force.

        @param reason  The ERR fields, e.g. "BADARG,window_s".
        """
        self.state_label.setText(f"RECHAZADA por el ESP32 ({reason}); "
                                 "sigue vigente la configuración anterior")
        self.state_label.setStyleSheet(REJECTED_STYLE)

    def _guard_last_variable(self) -> None:
        """@brief Make an empty selection impossible (spec 2.2: "rechazarse o impedirse").

        The only checked variable is disabled, so it cannot be unticked; ticking another one
        frees it again.
        """
        checked = [check for check in self.var_checks.values() if check.isChecked()]
        for check in self.var_checks.values():
            check.setEnabled(not (len(checked) == 1 and check.isChecked()))
