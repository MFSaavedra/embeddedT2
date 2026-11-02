"""@file test_firmware_host.py
@brief Build and run the firmware's pure-C modules on the host: no ESP32, no ESP-IDF.

Each check compiles firmware sources from esp32_firmware/main together with a test program
from tests/firmware/ using the host C compiler, runs it, and fails with the program's output
on a non-zero exit. Skipped when no C compiler is installed.

Only modules without ESP-IDF includes can be tested this way: protocol.c, sampler_cfg.c (the
CFG parser) and temp_proc.c (average and peaks). Spec tests 6.4 and 6.5 ask for exactly this
kind of evidence: a known series against a reference calculation. Tarea 1 kept
accel_sim_eval() "host-testable" but never built the harness; this file is that harness.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

## Repository root.
ROOT = pathlib.Path(__file__).resolve().parents[1]
## Firmware sources.
FW = ROOT / "esp32_firmware" / "main"
## Host-side C test programs.
TESTS_C = pathlib.Path(__file__).resolve().parent / "firmware"


def _host_env():
    """@brief The environment for the host compiler, without ESP-IDF's tool directories.

    With ESP-IDF activated, its cross binutils (an unprefixed `as` for the ULP, Xtensa and
    RISC-V targets) come first in PATH, and the host compiler would assemble with one of them
    ("as: unrecognized option '--64'"). Dropping those directories keeps `pytest` working in a
    shell where `idf.py` is also usable.

    @return A copy of os.environ with a filtered PATH.
    """
    tools = os.environ.get("IDF_TOOLS_PATH") or os.path.expanduser("~/.espressif")
    path = [d for d in os.environ.get("PATH", "").split(os.pathsep) if not d.startswith(tools)]
    return {**os.environ, "PATH": os.pathsep.join(path)}


## Environment the host compiler and the test programs run in.
HOST_ENV = _host_env()
## Host C compiler, or None.
CC = (shutil.which("cc", path=HOST_ENV["PATH"]) or shutil.which("gcc", path=HOST_ENV["PATH"])
      or shutil.which("clang", path=HOST_ENV["PATH"]))
## Strict flags: firmware code must build warning-free on the host as well.
CFLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-O1", f"-I{FW}"]

## Marker for tests that need CC.
needs_cc = pytest.mark.skipif(CC is None, reason="no host C compiler (cc / gcc / clang)")


def _compile(args):
    """@brief Run the host compiler; fail the test with its diagnostics on error.

    @param args  Arguments after the compiler and CFLAGS.
    """
    result = subprocess.run([CC, *CFLAGS, *map(str, args)], capture_output=True, text=True,
                            env=HOST_ENV)
    assert result.returncode == 0, result.stderr


def _run(exe):
    """@brief Run a test program; fail the test with its output on a non-zero exit.

    @param exe  Path of the program.
    """
    result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def _build_and_run(tmp_path, name, sources):
    """@brief Compile tests/firmware/<name>.c with firmware @p sources and run it.

    @param tmp_path  pytest's temporary directory.
    @param name      Test program name, without .c.
    @param sources   Firmware file names from esp32_firmware/main.
    """
    exe = tmp_path / name
    _compile([*(FW / s for s in sources), TESTS_C / f"{name}.c", "-lm", "-o", exe])
    _run(exe)


@needs_cc
def test_protocol_c_matches_the_python_reference(tmp_path):
    """@brief protocol.c produces and accepts exactly the bytes test_protocol.py expects."""
    _build_and_run(tmp_path, "test_protocol_c", ["protocol.c"])


@needs_cc
def test_temp_proc_average_and_peaks(tmp_path):
    """@brief UT1 + UT2: the moving average against a reference, peaks on known series."""
    _build_and_run(tmp_path, "test_temp_proc", ["temp_proc.c"])


@needs_cc
def test_sampler_cfg_parser(tmp_path):
    """@brief UT3: every invalid CFG is rejected, naming the field, and changes nothing."""
    _build_and_run(tmp_path, "test_sampler_cfg", ["sampler_cfg.c", "protocol.c"])
