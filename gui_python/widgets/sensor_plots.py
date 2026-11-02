"""@file sensor_plots.py
@brief Historical plots of T, H and P, one per variable (T2 spec 4, "Visualización"), with the
ESP32's results drawn on the temperature plot: its moving average, the threshold θ and the
detected peaks.

Adapted from Tarea 1's accel_plots.py, keeping its design:
- one numpy ring buffer of (t, value) per series; a jump of more than GAP_S between two
  samples (variable not transmitted, invalid readings) breaks the line instead of bridging it;
- push() is called from the serial signal for every sample and must only append;
- a single QTimer repaints the curves (REFRESH_MS) - never redraw per sample;
- the x axis is ESP32 time in seconds (t_ms / 1000), so a rate change shows up as
  denser or sparser points.

Differences from T1: one sample per push (T2 sends no batches), the y range autoscales,
units are written into the labels with pyqtgraph's SI-prefix scaling off (it would print
1012 hPa as "1.012 khPa"), a variable that is not being transmitted is marked as such in its
title (set_transmitted()), and the temperature plot has three extra items: the average
curve (series "avg"), the θ line and the peak markers. They come from the ESP32 even while
T itself is not transmitted (spec test 6.6).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QVBoxLayout, QWidget

## (key, title, unit) per plot, top to bottom.
PLOTS = (("T", "Temperatura", "°C"), ("H", "Humedad relativa", "%HR"), ("P", "Presión", "hPa"))
## Series key -> (plot it is drawn on, legend name or None, colour).
SERIES = {
    "T": ("T", "T medida", "#1f77b4"),
    "avg": ("T", "promedio móvil (ESP32)", "#ff7f0e"),
    "H": ("H", None, "#2ca02c"),
    "P": ("P", None, "#9467bd"),
}
## Redraw period in ms; samples arrive at 5 Hz at most, so 10 fps is plenty.
REFRESH_MS = 100
## Width of the sliding window in seconds.
DEFAULT_WINDOW_S = 120.0
## Highest sampling rate the buffers must hold, Hz.
MAX_RATE_HZ = 5
## Peak markers kept (older ones are long out of the window anyway).
MAX_PEAKS = 100
## A time jump longer than this between two samples of a series breaks its line, s. Longer
## than the slowest sampling period (2 s at 0.5 Hz).
GAP_S = 3.0


class SensorPlots(QWidget):
    """@brief Vertical stack of three pyqtgraph plots fed by per-series ring buffers.

    Producers call push(), push_avg() and add_peak(); the widget redraws itself from a QTimer,
    so the cost of a sample arriving is two array stores.
    """

    def __init__(self, parent=None):
        """@brief Allocate the ring buffers, create the plots and start the redraw timer.

        @param parent  Optional QWidget parent.
        """
        super().__init__(parent)
        ## Width of the sliding window in seconds.
        self.window_s = DEFAULT_WINDOW_S
        ## Ring buffer capacity in samples: twice the window at the highest rate.
        self._cap = int(DEFAULT_WINDOW_S * MAX_RATE_HZ) * 2
        ## Sample times in seconds (ESP32 clock), per series (ring buffer).
        self._t: Dict[str, np.ndarray] = {k: np.zeros(self._cap) for k in SERIES}
        ## Sample values, per series (ring buffer, parallel to _t).
        self._v: Dict[str, np.ndarray] = {k: np.zeros(self._cap) for k in SERIES}
        ## Next write position in the ring buffer, per series.
        self._idx: Dict[str, int] = {k: 0 for k in SERIES}
        ## Number of valid samples (saturates at _cap), per series.
        self._filled: Dict[str, int] = {k: 0 for k in SERIES}
        ## True when samples arrived since the last redraw, per series.
        self._dirty: Dict[str, bool] = {k: False for k in SERIES}
        ## Plot widget per plot key ("T", "H", "P").
        self._plots: Dict[str, pg.PlotWidget] = {}
        ## Curve item per series.
        self._curves: Dict[str, pg.PlotDataItem] = {}
        ## Plot title per plot key, without the "no transmitida" suffix.
        self._titles: Dict[str, str] = {}
        ## (time in s, °C) of the peaks received, oldest first.
        self._peaks: List[Tuple[float, float]] = []

        layout = QVBoxLayout(self)
        for key, title, unit in PLOTS:
            plot = pg.PlotWidget(title=title)
            for side in ("left", "bottom"):
                plot.getAxis(side).enableAutoSIPrefix(False)
            plot.setLabel("left", unit)               # the title names the variable
            plot.setLabel("bottom", "tiempo ESP32 [s]")
            plot.showGrid(x=True, y=True, alpha=0.3)
            self._plots[key] = plot
            self._titles[key] = title
            layout.addWidget(plot)

        temp_plot = self._plots["T"]
        # One row, top left, see-through: it explains the curves without hiding them.
        temp_plot.addLegend(offset=(10, 5), colCount=4, brush=pg.mkBrush(0, 0, 0, 170))
        for key, (plot_key, name, colour) in SERIES.items():
            self._curves[key] = self._plots[plot_key].plot(
                pen=pg.mkPen(colour, width=2 if key == "avg" else 1), name=name,
                symbol=None if key == "avg" else "o", symbolSize=4, symbolBrush=colour,
                symbolPen=None, connect="finite")
        ## Red markers on the peaks detected by the ESP32.
        self._peak_markers = pg.ScatterPlotItem(size=14, symbol="t1", pen=pg.mkPen("k"),
                                                brush=pg.mkBrush("#d62728"),
                                                name="pico (ESP32)")
        temp_plot.addItem(self._peak_markers)
        theta_pen = pg.mkPen("#d62728", width=1, style=Qt.DashLine)
        ## Horizontal line at the threshold θ in force; hidden while detection is off.
        self._theta_line = pg.InfiniteLine(angle=0, movable=False, pen=theta_pen)
        self._theta_line.setVisible(False)
        temp_plot.addItem(self._theta_line)
        ## Empty curve that only gives the θ line its legend entry (faded while it is hidden).
        self._theta_legend = temp_plot.plot([], [], pen=theta_pen, name="umbral θ")
        self._theta_legend.setVisible(False)

        ## Periodic redraw, REFRESH_MS.
        self._timer = QTimer(self)
        # Doxygen would read self._redraw as an attribute.
        # @cond
        self._timer.timeout.connect(self._redraw)
        # @endcond
        self._timer.start(REFRESH_MS)

    # --------------------------------- inputs ---------------------------------

    def push(self, key: str, t_ms: int, value: float) -> None:
        """@brief Append one sample of series @p key (called for every SMP that carries it).

        @param key    "T", "H", "P", or "avg" for the ESP32's moving average of T.
        @param t_ms   ESP32 timestamp of the measurement, ms.
        @param value  Measured value in the variable's unit.
        """
        t = t_ms / 1000.0
        last = self._t[key][(self._idx[key] - 1) % self._cap]
        if self._filled[key] and t - last > GAP_S:
            self._append(key, t, float("nan"))      # NaN: the curve is not drawn across the gap
        self._append(key, t, value)

    def _append(self, key: str, t: float, value: float) -> None:
        """@brief Store one point in the ring buffer of @p key.

        @param key    Series key.
        @param t      Time, s.
        @param value  Value, or NaN to break the line.
        """
        i = self._idx[key]
        self._t[key][i] = t
        self._v[key][i] = value
        self._idx[key] = (i + 1) % self._cap
        self._filled[key] = min(self._cap, self._filled[key] + 1)
        self._dirty[key] = True

    def add_peak(self, t_ms: int, peak_c: float) -> None:
        """@brief Mark a peak detected by the ESP32 on the temperature plot.

        @param t_ms    ESP32 time of the peak sample, ms.
        @param peak_c  Peak temperature, °C.
        """
        self._peaks = self._peaks[-(MAX_PEAKS - 1):] + [(t_ms / 1000.0, peak_c)]
        self._peak_markers.setData([t for t, _ in self._peaks], [v for _, v in self._peaks])

    def set_threshold(self, enabled: bool, threshold_c: float) -> None:
        """@brief Draw the threshold line at @p threshold_c, or hide it.

        @param enabled      Whether the ESP32 is detecting peaks.
        @param threshold_c  Threshold θ in force, °C.
        """
        self._theta_line.setValue(threshold_c)
        self._theta_line.setVisible(enabled)
        self._theta_legend.setVisible(enabled)

    def set_transmitted(self, key: str, transmitted: bool) -> None:
        """@brief Mark in the title whether @p key is currently selected for transmission.

        @param key          "T", "H" or "P".
        @param transmitted  False appends "no transmitida" to the title (spec 4).
        """
        title = self._titles[key]
        self._plots[key].setTitle(title if transmitted else f"{title} — no transmitida")

    def clear(self) -> None:
        """@brief Forget all samples and peaks and blank the curves (on connect / Inicializar)."""
        for key, curve in self._curves.items():
            self._idx[key] = 0
            self._filled[key] = 0
            self._dirty[key] = False
            curve.setData([], [])
        self._peaks = []
        self._peak_markers.setData([], [])

    def series(self, key: str) -> Tuple[np.ndarray, np.ndarray]:
        """@brief Retained samples of @p key in chronological order.

        @param key  "T", "H", "P" or "avg".
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

        Each plot shows the last window_s seconds before its newest sample (of any of its
        series), so it scrolls with the data.
        """
        for plot_key, plot in self._plots.items():
            keys = [k for k, (p, _name, _c) in SERIES.items() if p == plot_key]
            if not any(self._dirty[k] for k in keys):
                continue
            data = {k: self.series(k) for k in keys}
            t_last = max((t[-1] for t, _v in data.values() if t.size), default=None)
            if t_last is None:
                continue
            for k, (t, v) in data.items():
                self._dirty[k] = False
                mask = t >= t_last - self.window_s
                self._curves[k].setData(t[mask], v[mask])
            plot.setXRange(t_last - self.window_s, t_last, padding=0)
