"""@file sensor_plots.py
@brief Historical plots of T, H and P, one per variable (T2 spec 4, "Visualización").

Adapted from Tarea 1's accel_plots.py, keeping its design:
- one numpy ring buffer of (t, value) per variable;
- push() is called from the serial signal for every sample and must only append;
- a single QTimer repaints the curves (REFRESH_MS) - never redraw per sample;
- the x axis is ESP32 time in seconds (t_ms / 1000), so a rate change shows up as
  denser or sparser points.

Differences from T1: one sample per push (T2 sends no batches), the y range autoscales (there
is no amplitude to follow), units are written into the labels with pyqtgraph's SI-prefix
scaling off (it would print 1012 hPa as "1.012 khPa"), and a variable that is not being
transmitted can be marked as such (set_transmitted()).

TODO(PY5): overlay temp_avg_c on the temperature plot and mark PEAK events on it.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QVBoxLayout, QWidget

## (key, title, unit) per variable, top to bottom.
VARIABLES = (("T", "Temperatura", "°C"), ("H", "Humedad relativa", "%HR"), ("P", "Presión", "hPa"))
## Redraw period in ms; samples arrive at 5 Hz at most, so 10 fps is plenty.
REFRESH_MS = 100
## Width of the sliding window in seconds.
DEFAULT_WINDOW_S = 120.0
## Highest sampling rate the buffers must hold, Hz.
MAX_RATE_HZ = 5


class SensorPlots(QWidget):
    """@brief Vertical stack of three pyqtgraph plots fed by per-variable ring buffers.

    Producers call push(); the widget redraws itself from a QTimer, so the cost of a sample
    arriving is two array stores.
    """

    def __init__(self, parent=None):
        """@brief Allocate the ring buffers, create the plots and start the redraw timer.

        @param parent  Optional QWidget parent.
        """
        super().__init__(parent)
        keys = [key for key, _title, _unit in VARIABLES]
        ## Width of the sliding window in seconds.
        self.window_s = DEFAULT_WINDOW_S
        ## Ring buffer capacity in samples: twice the window at the highest rate.
        self._cap = int(DEFAULT_WINDOW_S * MAX_RATE_HZ) * 2
        ## Sample times in seconds (ESP32 clock), per variable (ring buffer).
        self._t: Dict[str, np.ndarray] = {k: np.zeros(self._cap) for k in keys}
        ## Sample values, per variable (ring buffer, parallel to _t).
        self._v: Dict[str, np.ndarray] = {k: np.zeros(self._cap) for k in keys}
        ## Next write position in the ring buffer, per variable.
        self._idx: Dict[str, int] = {k: 0 for k in keys}
        ## Number of valid samples (saturates at _cap), per variable.
        self._filled: Dict[str, int] = {k: 0 for k in keys}
        ## True when samples arrived since the last redraw, per variable.
        self._dirty: Dict[str, bool] = {k: False for k in keys}
        ## Plot widget per variable.
        self._plots: Dict[str, pg.PlotWidget] = {}
        ## Curve item per variable (the thing setData() is called on).
        self._curves: Dict[str, pg.PlotDataItem] = {}
        ## Plot title per variable, without the "no transmitida" suffix.
        self._titles: Dict[str, str] = {}

        layout = QVBoxLayout(self)
        for key, title, unit in VARIABLES:
            plot = pg.PlotWidget(title=title)
            for side in ("left", "bottom"):
                plot.getAxis(side).enableAutoSIPrefix(False)
            plot.setLabel("left", f"{title} [{unit}]")
            plot.setLabel("bottom", "tiempo ESP32 [s]")
            plot.showGrid(x=True, y=True, alpha=0.3)
            self._curves[key] = plot.plot(pen=pg.mkPen(width=1), symbol="o", symbolSize=4)
            self._plots[key] = plot
            self._titles[key] = title
            layout.addWidget(plot)

        ## Periodic redraw, REFRESH_MS.
        self._timer = QTimer(self)
        # Doxygen would read self._redraw as an attribute.
        # @cond
        self._timer.timeout.connect(self._redraw)
        # @endcond
        self._timer.start(REFRESH_MS)

    # --------------------------------- inputs ---------------------------------

    def push(self, key: str, t_ms: int, value: float) -> None:
        """@brief Append one sample of variable @p key (called for every SMP that carries it).

        @param key    "T", "H" or "P".
        @param t_ms   ESP32 timestamp of the measurement, ms.
        @param value  Measured value in the variable's unit.
        """
        i = self._idx[key]
        self._t[key][i] = t_ms / 1000.0
        self._v[key][i] = value
        self._idx[key] = (i + 1) % self._cap
        self._filled[key] = min(self._cap, self._filled[key] + 1)
        self._dirty[key] = True

    def set_transmitted(self, key: str, transmitted: bool) -> None:
        """@brief Mark in the title whether @p key is currently selected for transmission.

        @param key          "T", "H" or "P".
        @param transmitted  False appends "no transmitida" to the title (spec 4).
        """
        title = self._titles[key]
        self._plots[key].setTitle(title if transmitted else f"{title} — no transmitida")

    def clear(self) -> None:
        """@brief Forget all samples and blank the curves (on connect / Inicializar)."""
        for key, curve in self._curves.items():
            self._idx[key] = 0
            self._filled[key] = 0
            self._dirty[key] = False
            curve.setData([], [])

    def series(self, key: str) -> Tuple[np.ndarray, np.ndarray]:
        """@brief Retained samples of @p key in chronological order.

        @param key  "T", "H" or "P".
        @return (times in s, values), oldest first; empty arrays if nothing was pushed.
        """
        filled, idx = self._filled[key], self._idx[key]
        if filled < self._cap:
            return self._t[key][:filled].copy(), self._v[key][:filled].copy()
        return (np.concatenate((self._t[key][idx:], self._t[key][:idx])),
                np.concatenate((self._v[key][idx:], self._v[key][:idx])))

    # --------------------------------- redraw ---------------------------------

    def _redraw(self) -> None:
        """@brief Timer slot: repaint the plots that received samples since the last tick.

        Keeps only the last window_s seconds and scrolls the x range so the newest sample sits
        at the right edge.
        """
        for key, curve in self._curves.items():
            if not self._dirty[key]:
                continue
            self._dirty[key] = False
            t, v = self.series(key)
            if t.size == 0:
                continue
            t_last = t[-1]
            mask = t >= t_last - self.window_s
            curve.setData(t[mask], v[mask])
            self._plots[key].setXRange(t_last - self.window_s, t_last, padding=0)
