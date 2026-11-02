"""@file messages.py
@brief Meaning of the Tarea 2 messages (README.md "Protocolo"): builds CFG, decodes SMP, PEAK
and the configuration echoed by ACK,CFG.

protocol.py turns a line into its comma-separated fields; this module interprets them. Apart
from the message type, T2 fields are `key=value` pairs, because an SMP carries a different
set of variables depending on the selection, and each value travels labelled (the spec asks
for the average to be "etiquetado como temp_avg_c").

The firmware side of the same definitions is esp32_firmware/main/sampler_cfg.c (CFG) and
sampler.c (SMP, PEAK): change both together, with README.md.

No Qt here, so the tests use it directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

## Allowed sampling rates in Hz (spec 2.1.3). Same set as RATES in sampler_cfg.c.
RATES_HZ = (0.5, 1.0, 2.0, 5.0)
## Allowed average windows W in s (spec 3.1). Same set as WINDOWS_S in sampler_cfg.c.
WINDOWS_S = (5, 10, 30, 60)
## Lowest peak threshold, °C (PEAK_MIN_THRESHOLD_DC in app_config.h).
THRESHOLD_MIN_C = -40.0
## Highest peak threshold, °C (PEAK_MAX_THRESHOLD_DC in app_config.h).
THRESHOLD_MAX_C = 85.0
## SMP key of each variable letter, in display order.
SMP_KEYS = {"T": "temperature_c", "H": "humidity_pct", "P": "pressure_hpa"}


def parse_kv(fields: List[str]) -> Dict[str, str]:
    """@brief Turn `key=value` fields into a dict.

    @param fields  The fields after the message type (and after "CFG" for an ACK,CFG).
    @return {key: value} with the values still as text.
    @throws ValueError for a field without '=' or a repeated key.
    """
    kv: Dict[str, str] = {}
    for field in fields:
        key, sep, value = field.partition("=")
        if not sep or not key or key in kv:
            raise ValueError(f"campo inválido: {field!r}")
        kv[key] = value
    return kv


def _flag(text: str) -> bool:
    """@brief "0" / "1" -> bool.

    @param text  Field value.
    @return The flag.
    @throws ValueError for anything else.
    """
    if text not in ("0", "1"):
        raise ValueError(f"se esperaba 0 o 1: {text!r}")
    return text == "1"


@dataclass(frozen=True)
class Config:
    """@brief The ESP32's whole runtime configuration: what CFG sends and ACK,CFG echoes.

    The defaults are the spec's suggested initial values, the same as app_config.h, which
    is also what the firmware returns to on INIT.
    """

    ## Common sampling rate of T, H and P, Hz: one of RATES_HZ.
    sampling_hz: float = 1.0
    ## Variables transmitted, letters T / H / P in that order, never empty.
    variables: str = "THP"
    ## Moving average of T on the ESP32.
    avg_enabled: bool = False
    ## Average window W, s: one of WINDOWS_S.
    window_s: int = 10
    ## Peak detection on the ESP32.
    peak_enabled: bool = False
    ## Peak threshold θ, °C, 0.1 °C resolution.
    threshold_c: float = 28.0

    def payload(self) -> str:
        """@brief The CFG command: all six fields, in the order the firmware requires.

        @return e.g. "CFG,sampling_hz=2,variables=TP,avg_enabled=1,window_s=10,
                peak_enabled=1,threshold_c=28.0".
        """
        return (f"CFG,sampling_hz={self.sampling_hz:g},variables={self.variables},"
                f"avg_enabled={int(self.avg_enabled)},window_s={self.window_s},"
                f"peak_enabled={int(self.peak_enabled)},threshold_c={self.threshold_c:.1f}")

    def describe(self) -> str:
        """@brief One-line summary for the GUI, in Spanish.

        @return e.g. "2 Hz · T, P · promedio W = 10 s · picos θ = 28.0 °C".
        """
        avg = f"promedio W = {self.window_s} s" if self.avg_enabled else "promedio desactivado"
        peak = (f"picos θ = {self.threshold_c:.1f} °C" if self.peak_enabled
                else "picos desactivados")
        return f"{self.sampling_hz:g} Hz · {', '.join(self.variables)} · {avg} · {peak}"


def parse_config(fields: List[str]) -> Config:
    """@brief Decode the configuration echoed by `ACK,CFG,<fields>`.

    @param fields  The fields after "ACK","CFG".
    @return The configuration in force on the ESP32.
    @throws ValueError if a field is missing, unknown or malformed.
    """
    kv = parse_kv(fields)
    cfg = Config(sampling_hz=float(kv.pop("sampling_hz")),
                 variables=kv.pop("variables"),
                 avg_enabled=_flag(kv.pop("avg_enabled")),
                 window_s=int(kv.pop("window_s")),
                 peak_enabled=_flag(kv.pop("peak_enabled")),
                 threshold_c=float(kv.pop("threshold_c")))
    if kv:
        raise ValueError(f"campos desconocidos: {sorted(kv)}")
    return cfg


@dataclass(frozen=True)
class Sample:
    """@brief One SMP frame: one acquisition of the ESP32."""

    ## Sequence number; +1 per SMP since INIT, so a gap is a lost frame.
    seq: int
    ## ESP32 time of the measurement, ms since boot.
    t_ms: int
    ## Transmitted values by variable letter ("T" °C, "H" %HR, "P" hPa); only the selected ones.
    values: Dict[str, float]
    ## Moving average of T computed by the ESP32 (temp_avg_c), °C; None if not sent.
    avg_c: Optional[float] = None
    ## Number of samples N_W in that average; None if not sent.
    avg_n: Optional[int] = None
    ## Whether the samples already cover a whole window W; None if not sent.
    avg_complete: Optional[bool] = None
    ## Failure code ("no_sensor", "read_failed") of an invalid reading; None for a valid one.
    error: Optional[str] = None


def parse_sample(fields: List[str]) -> Sample:
    """@brief Decode an SMP frame.

    @param fields  All the frame's fields; fields[0] is "SMP".
    @return The sample.
    @throws ValueError (or KeyError for a missing seq / t_ms) if the frame is malformed.
    """
    kv = parse_kv(fields[1:])
    seq = int(kv.pop("seq"))
    t_ms = int(kv.pop("t_ms"))
    error = kv.pop("error", None)
    values = {var: float(kv.pop(key)) for var, key in SMP_KEYS.items() if key in kv}
    avg_c = avg_n = avg_complete = None
    if "temp_avg_c" in kv:
        avg_c = float(kv.pop("temp_avg_c"))
        avg_n = int(kv.pop("avg_n"))
        avg_complete = _flag(kv.pop("avg_window_complete"))
    if kv:
        raise ValueError(f"campos desconocidos: {sorted(kv)}")
    if error is not None and (values or avg_c is not None):
        raise ValueError("una lectura inválida no puede traer valores")
    return Sample(seq, t_ms, values, avg_c, avg_n, avg_complete, error)


@dataclass(frozen=True)
class Peak:
    """@brief One PEAK event: a temperature peak detected by the ESP32."""

    ## ESP32 time of the peak sample itself, ms since boot.
    t_ms: int
    ## Peak temperature, °C.
    peak_c: float
    ## Threshold θ applied when the peak was detected, °C.
    threshold_c: float


def parse_peak(fields: List[str]) -> Peak:
    """@brief Decode a PEAK frame.

    @param fields  All the frame's fields; fields[0] is "PEAK".
    @return The event.
    @throws ValueError (or KeyError for a missing field) if the frame is malformed.
    """
    kv = parse_kv(fields[1:])
    peak = Peak(int(kv.pop("t_ms")), float(kv.pop("peak_c")), float(kv.pop("threshold_c")))
    if kv:
        raise ValueError(f"campos desconocidos: {sorted(kv)}")
    return peak
