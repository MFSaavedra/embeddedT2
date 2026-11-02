# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Tarea 2 for CC5328 (Sistemas Embebidos y Sensores, U. de Chile). An ESP32 reads real
temperature, humidity and pressure from a BME688 over I2C, computes a time-window moving
average and peak events of the temperature **on the ESP32**, and streams only the selected
variables over UART0 to a PyQt5 GUI that reconfigures it live. Spec: `docs/Tarea2_CC5328.pdf`.

The repo was bootstrapped from Tarea 1 (`github.com/MFSaavedra/embeddedT1`, local
`../embeddedT1`). The framing, UART link, command dispatcher, SerialWorker, ConnectionPanel
and baud renegotiation are T1 code proven on this board; `TODO.md` "Carried over from T1"
says what came from where.

`README.md` is the authoritative (Spanish) spec of the protocol, wiring and design decisions.
`TODO.md` tracks grading, work items (`P1`, `FW*`, `PY*`, `UT*`, `MT*`), traps, T1 lessons and
open questions. README and GUI strings are in Spanish (course deliverable); code comments,
Doxygen text and `TODO.md` are in English.

**Status: scaffold.** The firmware builds, and the GUI connects, resets the board, INITs and
renegotiates the baud rate. Still TODO: BME688 measurement, the acquisition task, CFG,
processing and the T2 GUI panels.
**Deadline: Fri 6 Nov 2026, 23:59. Graded from an 8–12 min video (60 %) and code review (40 %).**

## Commands

### Firmware (`esp32_firmware/`, target `esp32`)

`idf.py` is **not** on PATH; activate it first in every shell. Two installs are in play:

```bash
. ~/aur_src/esp-idf/export.sh                 # this machine: ESP-IDF v5.5.5
# . ~/.espressif/tools/activate_idf_v6.1.sh   # the machine T1 was built on: ESP-IDF v6.1
cd esp32_firmware
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor          # Ctrl+] exits the monitor
rm sdkconfig && idf.py reconfigure            # after any change to sdkconfig.defaults
```

- The code must build on both v5.5 and v6.1. Use `driver/i2c_master.h`, not the legacy
  `driver/i2c.h`, and do not depend on the IDF-bundled `json` component.
- `sdkconfig` is generated and git-ignored; permanent config goes in `sdkconfig.defaults`.
- The monitor and the GUI cannot share `/dev/ttyUSB0`; close one before opening the other.
- No board has been attached in this environment yet, so firmware changes can be compiled
  here but not run.

### GUI and tests (Python 3.8+, PyQt5 + pyserial + pyqtgraph + numpy)

```bash
.venv/bin/python gui_python/main.py                       # run from repo root
.venv/bin/python -m pytest                                # everything under tests/ (pytest.ini)
.venv/bin/python -m pytest tests/test_protocol.py::test_round_trip
```

- `.venv/` (git-ignored) was created here with `python3 -m venv --system-site-packages .venv`
  plus `pip install pyqtgraph`. Elsewhere, use `pip install -r requirements.txt`. The file
  lives at the **repo root** (PDF section 8 deliverables), not in `gui_python/` as in T1.
- A system-wide `dash` pytest plugin prints a deprecation warning on this machine;
  `-p no:dash` silences it.
- Tests live in the root `tests/` (the PDF suggests that name), not in `gui_python/tests` as
  in T1:
  - `conftest.py` prepends `gui_python/` to `sys.path`, so tests `import protocol` exactly as
    the app does, and forces Qt's offscreen platform. Widget tests take the `qapp` fixture
    and call slots directly; there is no event loop.
  - `test_serial_worker.py` is the template for testing `SerialWorker` without hardware:
    monkeypatch `serial.Serial` with a fake port and connect signals with
    `Qt.DirectConnection`.
  - `test_main_window.py` tests the baud renegotiation state machine against a `StubWorker`.
  - `test_firmware_host.py` compiles firmware C with the host compiler
    (`-Wall -Wextra -Werror`) and runs `tests/firmware/test_*.c`. Only modules without
    ESP-IDF includes qualify: `protocol.c` now, `temp_proc.c` for UT1/UT2, and the pure CFG
    parser planned in FW3 for UT3. A test enforces that `temp_proc.c` stays host-compilable.

### Docs

Run `doxygen` from the repo root to get `docs/doxygen/html/`. T1 committed the generated HTML;
do the same once the code settles (DOC2). All C and Python code carries Doxygen comments
(`@file`, `@brief`, `@param`, `@return`). Python docstrings use the same `@` tags, and `##`
line comments document attributes and constants. Keep new code in that style.

Outstanding work is marked `TODO(<id>)` matching `TODO.md`:
`grep -rn "TODO(" esp32_firmware/main gui_python tests`.

## Architecture

### The protocol is implemented twice and must stay identical

`esp32_firmware/main/protocol.[ch]` and `gui_python/protocol.py` are mirrors: the frame is
`$<payload>*<XX>\n`, where `XX` is the XOR of the payload bytes as two hex digits.
`tests/firmware/test_protocol_c.c` checks the C side against the same bytes as
`tests/test_protocol.py`.

Message types and fields are *not* in the protocol layer. They live in README "Protocolo"
(the T2 fields are a DRAFT until P1) and are interpreted in `commands.c` (PC→ESP32: `CFG`,
`INIT`, `BAUD`) and `main_window.py::_on_frame` (ESP32→PC: `SMP`, `PEAK`, `ACK`, `ERR`).
Changing a message means touching README, both interpreters and the tests.

Paired constants that must be changed together:
- `LINK_BAUD` (`app_config.h`) ↔ `DEFAULT_BAUD` (`widgets/connection_panel.py`) ↔
  `CONFIG_ESP_CONSOLE_UART_BAUDRATE` (`sdkconfig.defaults`), all 921600. This is the *boot*
  speed: the GUI always opens the port at it because it resets the board on every connect.
- `BAUD_RATES` (`connection_panel.py`) ↔ `uart_link_valid_baud()` (`uart_link.c`).
- `LINK_BAUD_REVERT_MS` 5 s (`app_config.h`) < `BAUD_NEGOTIATION_MS` 8 s (`main_window.py`).
- Sampling/processing defaults and allowed sets (`app_config.h`, `sampler_valid_*()`) ↔ the
  GUI panels to come (PY3).
- BME688 pins and addresses (`app_config.h`) ↔ README "Conexión física".

### Firmware data flow (`esp32_firmware/main/`)

```
app_main: uart_link_init → bme688_init (probe 0x77/0x76 + chip id; failure not fatal)
          → sampler_init → uart_link_start_rx_task(commands_handle_line)

uart_rx task ──line──▶ commands_handle_line ──▶ proto_parse/split ──▶ handle_cfg | handle_init | handle_baud ──▶ ACK/ERR
acquisition task (TODO FW2) ──▶ bme688_read ──▶ temp_proc (always T) ──▶ SMP (selected vars) / PEAK ──▶ uart_link_send_frame
```

- Acquisition starts only on INIT: stop → reset defaults → `ACK,INIT,<FW_VERSION>` → start.
  The ACK goes out before any data so the GUI can reset on it. BAUD stops acquisition; the
  INIT that confirms the new rate restarts it.
- `sampler_cfg_t` is the whole runtime config. `sampler_set_config()` validates every field,
  then copies under a critical section, because the RX task writes it and the acquisition
  task reads it. Readers take snapshots (`sampler_get_config()`). A bad CFG changes nothing
  (spec 5).
- `bme688` is not thread-safe. After boot, only the acquisition task may call it, retries
  included (FW6). That is why `handle_init()` does not re-init the sensor from the RX task.
- `bme688_read()` blocks for the conversion: never call it from an esp_timer callback. A
  failed read must not produce anything that looks like a measurement (spec 2.1.2).
- `temp_proc.c` is pure C (no ESP-IDF, no clock, caller-owned state) so the host can test it.
- UART0 carries both frames and `ESP_LOG`. `uart_vfs_dev_use_driver()` keeps log lines from
  being spliced into frames; never `printf` a `$`-prefixed line outside
  `uart_link_send_frame()`.
- `commands.c`: `parse_field()` does strict integer parsing with bounds before narrowing.
  `BADARG` is for content errors, `BADFRAME` only for framing/checksum failures, and
  `NOTIMPL` marks stubs (CFG until FW3).

### GUI data flow (`gui_python/`)

```
widgets (Qt signals) ──▶ MainWindow._send_*() ──▶ SerialWorker.send(payload)
SerialWorker(QThread).run() readline ──▶ frame_received / bad_line ──▶ MainWindow._on_frame ──▶ ReadingsPanel / SensorPlots
```

Invariants carried over from T1 (do not break them):
- `serial_worker.py` is the only module that imports pyserial. `main_window.py` is the only
  one that knows both the widgets and the worker; widgets never see the port.
- All serial I/O runs on the `QThread`, and results reach the GUI only through signals.
  `send()` is callable from any thread. No exception may escape `run()`.
- `run()` pulses EN (DTR off, RTS on 100 ms, RTS off), then reads for `BOOT_WAIT_S` before
  emitting `connected`. A plain open hangs the CP2102 board most of the time (measured 1–4
  usable connects out of 10 vs 10/10 with the pulse). Do not remove it or move it to `open()`.
- Baud renegotiation is ordered, not simultaneous: `$BAUD` → the firmware stops acquisition,
  ACKs at the old rate, drains TX and switches → the GUI switches on that ACK (deferred to
  the read loop by `request_baud()`) → the GUI sends `$INIT`. Both ends auto-revert if the
  other goes silent. The selector is never the opening speed.
- `ConnectionPanel._apply_enabled_state()` is the only place that enables or disables its
  controls.
- GUI state is reset on `ACK,INIT`, not when INIT is sent. The OK/rejected counters are
  mutually exclusive: a frame with a valid checksum but malformed fields counts as rejected.
- `_on_frame` aborts a pending renegotiation on any `ERR`, so do not use `ERR` for
  asynchronous sensor faults (P1).
- Plots: `push()` only appends to numpy ring buffers and a `QTimer` redraws; never redraw per
  sample. pyqtgraph's auto SI prefix is off, because it would print 1012 hPa as "1.012 khPa".

## Conventions

- Firmware module layout: `<module>.h` holds the public API with full Doxygen; `<module>.c`
  keeps module state in `static` variables prefixed `s_`, with static helpers documented
  inline. New sources go in `main/CMakeLists.txt` `SRCS`. New ESP-IDF components go in its
  `PRIV_REQUIRES`: `MINIMAL_BUILD` is ON, so an unlisted component is not compiled. A
  vendored Bosch BME68x API (`components/bme68x`) must be listed too.
- Signal-flow comments at the top of Python modules describe the real wiring; update them
  when the wiring changes.
- Widget wiring in `MainWindow.__init__` is wrapped in `# @cond` / `# @endcond` so Doxygen
  does not misread bound-method connects as attributes.
- Commit messages are plain (no Co-Authored-By / session trailers).
