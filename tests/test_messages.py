"""@file test_messages.py
@brief The T2 message fields (messages.py): CFG building, and SMP / PEAK / ACK,CFG decoding.

The CFG strings expected here are the ones tests/firmware/test_sampler_cfg.c makes the
firmware accept and echo, so the two sides of the CFG command cannot drift apart.
"""
import pytest

import messages
from messages import Config, Peak, Sample


def test_default_config_payload_matches_the_firmware_defaults():
    """@brief Config() is the firmware's default (sampler_cfg_default()), field by field."""
    assert Config().payload() == ("CFG,sampling_hz=1,variables=THP,avg_enabled=0,window_s=10,"
                                  "peak_enabled=0,threshold_c=28.0")


def test_config_payload_of_the_spec_example():
    """@brief The README / spec example: 2 Hz, T and P, average and peaks on."""
    cfg = Config(sampling_hz=2.0, variables="TP", avg_enabled=True, window_s=10,
                 peak_enabled=True, threshold_c=28.0)
    assert cfg.payload() == ("CFG,sampling_hz=2,variables=TP,avg_enabled=1,window_s=10,"
                             "peak_enabled=1,threshold_c=28.0")


def test_config_payload_formats_rates_and_thresholds_like_the_firmware():
    """@brief 0.5 Hz keeps its decimal, whole rates do not; θ always has exactly one decimal."""
    cfg = Config(sampling_hz=0.5, variables="H", window_s=5, threshold_c=-0.5)
    assert "sampling_hz=0.5," in cfg.payload()
    assert cfg.payload().endswith("threshold_c=-0.5")
    assert Config(threshold_c=28.1).payload().endswith("threshold_c=28.1")
    assert Config(threshold_c=85.0).payload().endswith("threshold_c=85.0")


def test_parse_config_reads_back_the_ack_echo():
    """@brief ACK,CFG echoes the fields in the payload's form; decoding gives the same Config."""
    cfg = Config(sampling_hz=5.0, variables="HP", avg_enabled=True, window_s=60,
                 peak_enabled=False, threshold_c=-40.0)
    fields = cfg.payload().split(",")[1:]
    assert messages.parse_config(fields) == cfg


@pytest.mark.parametrize("fields", [
    ["sampling_hz=1", "variables=T"],                                     # missing keys
    ["sampling_hz=1", "variables=T", "avg_enabled=2", "window_s=10",
     "peak_enabled=0", "threshold_c=28.0"],                               # bad flag
    ["sampling_hz=1", "variables=T", "avg_enabled=0", "window_s=10",
     "peak_enabled=0", "threshold_c=28.0", "extra=1"],                    # unknown key
])
def test_parse_config_rejects_malformed_echoes(fields):
    """@brief A malformed echo raises, so MainWindow counts the frame as rejected."""
    with pytest.raises((ValueError, KeyError)):
        messages.parse_config(fields)


def test_parse_sample_with_every_field():
    """@brief All variables plus the average, as in the README example."""
    s = messages.parse_sample(
        "SMP,seq=145,t_ms=73210,temperature_c=26.40,humidity_pct=54.10,pressure_hpa=1012.70,"
        "temp_avg_c=26.10,avg_n=20,avg_window_complete=1".split(","))
    assert s == Sample(seq=145, t_ms=73210, values={"T": 26.4, "H": 54.1, "P": 1012.7},
                       avg_c=26.1, avg_n=20, avg_complete=True)


def test_parse_sample_with_hidden_temperature_still_has_the_average():
    """@brief Spec 6.6: only H selected, yet the ESP32's average of T arrives."""
    s = messages.parse_sample(
        "SMP,seq=3,t_ms=4000,humidity_pct=55.00,temp_avg_c=24.11,avg_n=4,avg_window_complete=0"
        .split(","))
    assert s.values == {"H": 55.0}
    assert s.avg_c == 24.11 and s.avg_n == 4 and s.avg_complete is False
    assert s.error is None


def test_parse_sample_invalid_reading_has_no_values():
    """@brief Spec 2.1.2: a failed reading carries an error code and nothing that looks measured."""
    s = messages.parse_sample("SMP,seq=7,t_ms=9000,error=no_sensor".split(","))
    assert s.error == "no_sensor" and s.values == {} and s.avg_c is None


@pytest.mark.parametrize("line", [
    "SMP,t_ms=1000,temperature_c=24.0",                     # no seq
    "SMP,seq=1,temperature_c=24.0",                          # no t_ms
    "SMP,seq=x,t_ms=1000",                                   # seq not a number
    "SMP,seq=1,t_ms=1000,temperature_c=hot",                 # value not a number
    "SMP,seq=1,t_ms=1000,temperature_c",                     # field without '='
    "SMP,seq=1,seq=2,t_ms=1000",                             # repeated key
    "SMP,seq=1,t_ms=1000,wind_kmh=3.0",                      # unknown key
    "SMP,seq=1,t_ms=1000,temp_avg_c=24.0",                   # average without its N and flag
    "SMP,seq=1,t_ms=1000,error=read_failed,temperature_c=24.0",  # error with a value
])
def test_parse_sample_rejects_malformed_frames(line):
    """@brief Anything malformed raises, so MainWindow counts it as rejected."""
    with pytest.raises((ValueError, KeyError)):
        messages.parse_sample(line.split(","))


def test_parse_peak():
    """@brief PEAK carries the peak's own time, its value and the threshold applied."""
    assert messages.parse_peak("PEAK,t_ms=75410,peak_c=28.70,threshold_c=28.0".split(",")) == \
        Peak(t_ms=75410, peak_c=28.7, threshold_c=28.0)
    with pytest.raises((ValueError, KeyError)):
        messages.parse_peak("PEAK,t_ms=75410,peak_c=28.70".split(","))


def test_describe_is_readable():
    """@brief The one-line summary shown under "Configuración vigente en el ESP32"."""
    assert Config().describe() == ("1 Hz · T, H, P · promedio desactivado · "
                                   "picos desactivados")
    cfg = Config(sampling_hz=0.5, variables="TP", avg_enabled=True, window_s=30,
                 peak_enabled=True, threshold_c=24.5)
    assert cfg.describe() == "0.5 Hz · T, P · promedio W = 30 s · picos θ = 24.5 °C"
