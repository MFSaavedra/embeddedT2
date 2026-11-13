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

**Status: complete, verified on the real board (2026-11-02).** Firmware and GUI do everything
in the PDF; README "Pruebas obligatorias" has the procedures and results, and
`video_demostracion.mp4` (9:13, captions, looped background music, recorded from the real GUI on the real board,
with three phone shots of the setup inserted) is the demo video. Left: add the teammate to the repo, re-check the build on ESP-IDF v5.5, optionally
commit the Doxygen HTML (DOC2; `doxygen` is not installed on the v6.1 machine).
**Deadline: Fri 6 Nov 2026, 23:59. Graded from an 8–12 min video (60 %) and code review (40 %).**

## Commands

### Firmware (`esp32_firmware/`, target `esp32`)

`idf.py` is **not** on PATH; activate it first in every shell. The team works on two
machines with different installs (`ls ~/.espressif ~/aur_src` tells which one you are on):

```bash
. ~/.espressif/tools/activate_idf_v6.1.sh     # machine with the board attached: ESP-IDF v6.1
# . ~/aur_src/esp-idf/export.sh               # the other machine: ESP-IDF v5.5.5
cd esp32_firmware
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor          # Ctrl+] exits the monitor
rm sdkconfig && idf.py reconfigure            # after any change to sdkconfig.defaults
```

- The code must build on both v5.5 and v6.1 (zero warnings; the final T2 code was verified
  on v6.1 only, re-check v5.5 on the other machine). Use
  `driver/i2c_master.h`, not the legacy `driver/i2c.h`, and do not depend on the IDF-bundled
  `json` component.
- `sdkconfig` is generated and git-ignored; permanent config goes in `sdkconfig.defaults`.
- The monitor and the GUI cannot share `/dev/ttyUSB0`; close one before opening the other.
- The board (ESP32 DevKit, CP2102, `/dev/ttyUSB0`) and the BME688 are attached to the v6.1
  machine, so firmware can be flashed and run there. A good boot logs
  `bme688: BME688 found at 0x76 (chip id 0x61, variant 0x01)`.
- `idf.py monitor` needs an interactive terminal. From a non-interactive shell, open the port
  with pyserial at 921600 after the same EN pulse the GUI uses (DTR off, RTS on 100 ms, RTS
  off). The first read right after `idf.py flash` can come back empty; retry.
- `../bme688_test` (local to the v6.1 machine, **not in this repo**) is a standalone ESP-IDF
  bring-up test of the sensor: wiring, chip id, conversion time, T/H/P plausibility, heater.
  `esp32_firmware/components/bme68x` (Bosch SensorAPI v4.4.8, unmodified) was copied from it.
  Its numbers are in `TODO.md` "Measured on the real sensor".

### GUI and tests (Python 3.8+, PyQt5 + pyserial + pyqtgraph + numpy)

```bash
.venv/bin/python gui_python/main.py                       # run from repo root
.venv/bin/python -m pytest                                # everything under tests/ (pytest.ini)
.venv/bin/python -m pytest tests/test_protocol.py::test_round_trip
```

- `.venv/` (git-ignored) exists on both machines, made with
  `python3 -m venv --system-site-packages .venv` (system PyQt5) plus pip: pyqtgraph on the
  v5.5 machine; pyserial, pyqtgraph and pytest on the v6.1 machine (Python 3.11).
  `requirements.txt` lives at the **repo root** (PDF section 8 deliverables), not in
  `gui_python/` as in T1.
- A system-wide `dash` pytest plugin prints a deprecation warning on the v5.5 machine;
  `-p no:dash` silences it.
- Tests live in the root `tests/` (the PDF suggests that name), not in `gui_python/tests` as
  in T1:
  - `conftest.py` prepends `gui_python/` to `sys.path`, so tests `import protocol` exactly as
    the app does, and forces Qt's offscreen platform. Widget tests take the `qapp` fixture
    and call slots directly; there is no event loop.
  - `test_serial_worker.py` is the template for testing `SerialWorker` without hardware:
    monkeypatch `serial.Serial` with a fake port and connect signals with
    `Qt.DirectConnection`.
  - `test_main_window.py` drives `MainWindow` against a `StubWorker`: the baud renegotiation
    state machine, SMP / PEAK / ACK / ERR routing, the CFG lifecycle, the "sin datos"
    watchdog and the automatic reconnection.
  - `test_firmware_host.py` compiles firmware C with the host compiler
    (`-Wall -Wextra -Werror`) and runs `tests/firmware/test_*.c`. Only modules without
    ESP-IDF includes qualify: `protocol.c`, `temp_proc.c` (UT1/UT2: average vs. a reference,
    peaks on known series) and `sampler_cfg.c` (UT3: every invalid CFG). `app_config.h`
    includes nothing so these modules can use it on the host; keep it that way. The harness
    drops ESP-IDF's tool dirs from PATH (the v6.1 activate script puts an unprefixed cross
    `as` there, which breaks the host `cc`), so `pytest` also works in an IDF shell.
  - `test_messages.py` checks the GUI's CFG strings against the same literals
    `test_sampler_cfg.c` makes the firmware accept, so the two sides cannot drift.
- Hardware checks without the GUI: open `/dev/ttyUSB0` with pyserial at 921600, pulse EN
  (DTR off, RTS on 100 ms, RTS off), wait ~1.2 s, then send `protocol.build_frame("INIT")`
  and CFG payloads and read lines. The whole GUI can also run against the board offscreen
  (`QT_QPA_PLATFORM=offscreen`), driving its widgets from `QTimer.singleShot` and saving
  `window.grab()` screenshots; that is how `docs/screenshots/` was made.

### Docs

Run `doxygen` from the repo root to get `docs/doxygen/html/`. T1 committed the generated HTML;
do the same once the code settles (DOC2). All C and Python code carries Doxygen comments
(`@file`, `@brief`, `@param`, `@return`). Python docstrings use the same `@` tags, and `##`
line comments document attributes and constants. Keep new code in that style.

Outstanding work is marked `TODO(<id>)` matching `TODO.md`:
`grep -rn "TODO(" esp32_firmware/main gui_python tests` (empty as of 2026-11-02).

## Architecture

### The protocol is implemented twice and must stay identical

`esp32_firmware/main/protocol.[ch]` and `gui_python/protocol.py` are mirrors: the frame is
`$<payload>*<XX>\n`, where `XX` is the XOR of the payload bytes as two hex digits.
`tests/firmware/test_protocol_c.c` checks the C side against the same bytes as
`tests/test_protocol.py`.

Message types and fields are *not* in the protocol layer. They live in README "Protocolo" and
are interpreted on the firmware by `sampler_cfg.c` (CFG fields), `commands.c` (dispatch of
`CFG`, `INIT`, `BAUD`) and `sampler.c` (builds `SMP`, `PEAK`), and on the GUI by
`messages.py` (builds CFG, decodes SMP / PEAK / the ACK,CFG echo) and
`main_window.py::_on_frame` (routing). T2 fields are `key=value`; CFG carries all six keys in a
fixed order. Changing a message means touching README, both interpreters and the tests.

Paired constants that must be changed together:
- `LINK_BAUD` (`app_config.h`) ↔ `DEFAULT_BAUD` (`widgets/connection_panel.py`) ↔
  `CONFIG_ESP_CONSOLE_UART_BAUDRATE` (`sdkconfig.defaults`), all 921600. This is the *boot*
  speed: the GUI always opens the port at it because it resets the board on every connect.
- `BAUD_RATES` (`connection_panel.py`) ↔ `uart_link_valid_baud()` (`uart_link.c`).
- `LINK_BAUD_REVERT_MS` 5 s (`app_config.h`) < `BAUD_NEGOTIATION_MS` 8 s (`main_window.py`).
- Sampling/processing defaults and allowed sets (`app_config.h`; `RATES` / `WINDOWS_S` in
  `sampler_cfg.c`) ↔ `messages.py` (`Config` defaults, `RATES_HZ`, `WINDOWS_S`,
  `THRESHOLD_MIN_C` / `THRESHOLD_MAX_C`).
- BME688 pins and addresses (`app_config.h`) ↔ README "Conexión física".

### Firmware data flow (`esp32_firmware/main/`)

```
app_main: uart_link_init → bme688_init (probe 0x76/0x77, Bosch init; failure not fatal)
          → sampler_init (defaults + acquisition task) → uart_link_start_rx_task(commands_handle_line)

uart_rx task ──line──▶ commands_handle_line ──▶ proto_parse/split ──▶ handle_cfg | handle_init | handle_baud ──▶ ACK/ERR
                                                                     (sampler_cfg_parse)
acquisition task ──▶ [re-init if not ready] bme688_read ──▶ temp_proc (always T) ──▶ SMP (selected vars) / PEAK ──▶ uart_link_send_frame
                └──▶ on failure: SMP,seq,t_ms,error=no_sensor|read_failed (no values)
```

- Acquisition starts only on INIT: stop → reset defaults → `ACK,INIT,<FW_VERSION>` → start.
  The ACK goes out before any data so the GUI can reset on it. BAUD stops acquisition; the
  INIT that confirms the new rate restarts it.
- `sampler_cfg_t` (`sampler_cfg.h`) is the whole runtime config; `sampler_cfg_parse()`
  validates all six CFG fields before anything is applied, so a bad CFG changes nothing
  (spec 5). `sampler.c` keeps the live copy behind one FreeRTOS mutex that the acquisition
  task holds for a whole cycle (read, process, send): a CFG applies between two readings, and
  `sampler_stop()` returns only when no acquisition frame can still be sent (BAUD relies on
  that). Never take that mutex from an esp_timer callback or ISR.
- `bme688` is not thread-safe. After boot, only the acquisition task may call it, retries
  included (FW6). That is why `handle_init()` does not re-init the sensor from the RX task.
- `bme688_read()` blocks for the conversion (40.3 ms measured with T×2 / P×16 / H×1; the wait
  is `bme68x_get_meas_dur()` rounded UP to ticks + 1): never call it from an esp_timer
  callback. A failed or implausible read marks the sensor not ready, the next cycle
  re-initialises it, and nothing that looks like a measurement is sent (spec 2.1.2).
- `temp_proc.c` is pure C (no ESP-IDF, no clock, caller-owned state) so the host can test it.
  Both algorithms are fed every reading; the enable flags only gate what is sent. The peak
  detector uses a hysteresis of `PEAK_HYSTERESIS_C` (0.2 °C, 10× the measured noise): a
  maximum is confirmed once T falls 0.2 °C below it; README "Detección de picos" explains why.
- UART0 carries both frames and `ESP_LOG`. `uart_vfs_dev_use_driver()` keeps log lines from
  being spliced into frames; never `printf` a `$`-prefixed line outside
  `uart_link_send_frame()`.
- `commands.c`: `parse_field()` does strict integer parsing with bounds before narrowing.
  `BADARG` is for content errors (`ERR,BADARG,<key>` names the first bad CFG field), and
  `BADFRAME` only for framing/checksum failures.

### GUI data flow (`gui_python/`)

```
widgets (Qt signals) ──▶ MainWindow._send_*() ──▶ SerialWorker.send(payload)
SerialWorker(QThread).run() readline ──▶ frame_received / bad_line ──▶ MainWindow._on_frame
    ──▶ messages.parse_*() ──▶ ReadingsPanel / SensorPlots / PeakPanel / ConfigPanel / status bar
```

Widgets: `ConnectionPanel` (T1, plus a reconnecting state), `ConfigPanel` (one CFG per
Aplicar; shows pending / confirmed / rejected and the ESP32's echo), `ReadingsPanel` (values,
"no transmitida", ESP32 average with a PC recomputation labelled as validation, valid /
invalid / "sin datos", seq / Δt / lost frames), `PeakPanel` (history + θ), `SensorPlots`
(T/H/P, average curve, θ line and peak markers on T), `CommandBox` (manual payloads, to
demo an invalid CFG).

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
- `_on_frame` aborts a pending renegotiation on any `ERR`, so sensor faults travel as
  `SMP,...,error=` and never as `ERR`. It decodes before touching any widget, so a malformed
  frame changes nothing and counts as rejected.
- Nothing is shown as applied before the ESP32 confirms it: panels follow `ACK,CFG` and
  `ACK,INIT`. INIT resets the firmware to its defaults, so after an INIT the user did not ask
  for (automatic reconnection, baud change) MainWindow re-sends the confirmed config
  (`_restore_cfg`).
- A disconnect the user did not ask for (`_want_connected` still set) is retried every
  `RECONNECT_INTERVAL_MS`; Desconectar / Cancelar reconexión stops it.
- Plots: `push()` only appends to numpy ring buffers and a `QTimer` redraws; never redraw per
  sample. pyqtgraph's auto SI prefix is off, because it would print 1012 hPa as "1.012 khPa".
  A time gap > `GAP_S` inserts a NaN so lines are not drawn across untransmitted stretches.

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
