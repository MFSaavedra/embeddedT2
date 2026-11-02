"""@file test_firmware_host.py
@brief Build and run the firmware's pure-C modules on the host: no ESP32, no ESP-IDF.

Each check compiles firmware sources from esp32_firmware/main together with a test program
from tests/firmware/ using the host C compiler, runs it, and fails with the program's output
on a non-zero exit. Skipped when no C compiler is installed.

Only modules without ESP-IDF includes can be tested this way: protocol.c now, temp_proc.c
once FW4/FW5 land - spec tests 6.4 and 6.5 ask for exactly this kind of evidence (a known
series against a reference calculation). Tarea 1 kept accel_sim_eval() "host-testable" but
never built the harness; this file is that harness.
"""
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
## Host C compiler, or None.
CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
## Strict flags: firmware code must build warning-free on the host as well.
CFLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-O1", f"-I{FW}"]

## Marker for tests that need CC.
needs_cc = pytest.mark.skipif(CC is None, reason="no host C compiler (cc / gcc / clang)")


def _compile(args):
    """@brief Run the host compiler; fail the test with its diagnostics on error.

    @param args  Arguments after the compiler and CFLAGS.
    """
    result = subprocess.run([CC, *CFLAGS, *map(str, args)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _run(exe):
    """@brief Run a test program; fail the test with its output on a non-zero exit.

    @param exe  Path of the program.
    """
    result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@needs_cc
def test_protocol_c_matches_the_python_reference(tmp_path):
    """@brief protocol.c produces and accepts exactly the bytes test_protocol.py expects."""
    exe = tmp_path / "test_protocol_c"
    _compile([FW / "protocol.c", TESTS_C / "test_protocol_c.c", "-o", exe])
    _run(exe)


@needs_cc
def test_temp_proc_compiles_on_the_host(tmp_path):
    """@brief temp_proc.c must stay free of ESP-IDF includes so it can be unit-tested here."""
    _compile(["-c", FW / "temp_proc.c", "-o", tmp_path / "temp_proc.o"])
