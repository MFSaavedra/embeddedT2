# TODO — Tarea 2 CC5328 (BME688 → ESP32 → PyQt)

**Deadline: Friday 6 November 2026, 23:59.** Deliver a Git repo link or ZIP, with README and
the demo video (file or link). Grading: **code review 40 % (2.4 pts) + demo video 60 %
(3.6 pts)**, scale 1.0–7.0 (base 1.0 + up to 6.0). There is **no live demo**: grading is done
from the 8–12 min video, so every point has to be *visible* in it. Build for the recording.

Item IDs (`P1`, `FW2`, `PY4`, `UT1`, `MT3`, …) used to match `TODO(<id>)` comments in the
code. **Status 2026-11-02: every code item is done and verified on the real board, and the demo
video is in the repo (`video_demostracion.mp4`); no `TODO(` marker is left.** What remains:
the teammate's repo access, the v5.5 build check, and optionally the Doxygen HTML (DOC2).

Recommended order (PDF section 9): I²C + valid readings → serial → GUI → reconfiguration →
average and peaks → robustness. Never assume a command took effect before its ACK arrives.

---

## 0. Setup

- [x] Repo bootstrapped from Tarea 1 (see "Carried over from T1" below)
- [x] Firmware builds on ESP-IDF v5.5.5 (`~/aur_src` machine), zero warnings in `main/`.
      `bme688_init()` probes the bus and checks the chip id; measurement, acquisition task,
      CFG and processing are stubs
- [x] GUI launches; `pytest` passes: protocol in Python **and in C on the host**,
      SerialWorker against a fake port, baud renegotiation, adapted widgets
- [ ] Teammate added to the private repo:
      `gh api -X PUT repos/MFSaavedra/embeddedT2/collaborators/<github-user>`
- [x] Firmware also builds on ESP-IDF v6.1 (the machine with the board), zero warnings
      (2026-11-02)
- [ ] Re-check the **final** firmware on ESP-IDF v5.5 (`~/aur_src` machine): only v6.1 is
      installed where the T2 code was written. It uses no API newer than v5.5 (plain
      `i2c_master_transmit()`, not the multi-buffer call), but that is unverified
- [x] BME688 breakout wired as in README "Conexión física"; every boot logs
      `bme688: BME688 found at 0x76 (chip id 0x61, variant 0x01)` (2026-11-02). The local
      `../bme688_test` bring-up test passes all its checks (see "Measured on the real sensor")

## 1. Protocol

- [x] **P1** Framing: T1's `$payload*XX` kept (implemented and tested on both sides, no JSON
      parser on the ESP32; the PDF allows "texto delimitado")
- [x] **P1** Fields frozen in README "Protocolo": `key=value` fields; CFG carries all six keys
      in a fixed order and is echoed by `ACK,CFG`; SMP = `seq`, `t_ms`, the selected variables,
      plus `temp_avg_c`, `avg_n`, `avg_window_complete` when the average is on; `PEAK,t_ms,
      peak_c,threshold_c`; errors `BADFRAME`, `EMPTY`, `UNKNOWN`, `BADARG[,<key>]`
- [x] **P1** Sensor faults: `SMP,seq,t_ms,error=no_sensor|read_failed`, never `ERR`
- [x] **P1** README, `sampler_cfg.c` / `commands.c` / `sampler.c`, `messages.py` /
      `main_window.py` and the tests all agree; `test_messages.py` and `test_sampler_cfg.c`
      share the CFG literals

## 2. Firmware — `esp32_firmware/main/`

- [x] **FW1** `bme688.c` on the Bosch SensorAPI (`components/bme68x`, copied from
      `../bme688_test`): forced mode, T×2 / P×16 / H×1, IIR off, heater disabled; waits
      `bme68x_get_meas_dur()` (42.6 ms) rounded up to ticks + 1; the API checks new_data;
      out-of-range values are treated as a failed read. Plain `i2c_master_transmit()` with a
      21-byte copy in the write callback (no `i2c_master_multi_buffer_transmit()`, whose
      availability on v5.5 was not checked)
- [x] **FW2** Acquisition task in `sampler.c`: priority 5, 4 KB stack, `xTaskDelayUntil()`
      with the period re-read every cycle; `t_ms` at the start of the measurement; `seq` +1
      per SMP (errors included); T always into temp_proc; one mutex held per cycle, so CFG
      applies between readings and `sampler_stop()` leaves nothing pending
- [x] **FW3** CFG: `sampler_cfg.[ch]` (pure C) parses the six fields strictly (rate table,
      letters without repeats, 0/1 flags, W in {5, 10, 30, 60}, θ with exactly one decimal
      converted to tenths without float) and formats the echo; `handle_cfg()` replies
      `ACK,CFG,<config in force>` or `ERR,BADARG,<first bad key>`
- [x] **FW4** Moving average: window `(t − W, t]`, 320 retained samples whatever W is,
      complete once `t − t_first ≥ W`, `N_W` sent as `avg_n`
- [x] **FW5** Peaks: hysteresis h = 0.2 °C (`PEAK_HYSTERESIS_C`, 10× the noise): a maximum is
      confirmed once T falls h below it, the next rise needs h above the minimum; reported if
      ≥ θ, with the peak sample's own time. Satisfies the minimum rule; README explains it
- [x] **FW6** Faults: a failed read or init gives `error=...` SMPs; the acquisition task
      re-initialises the sensor every cycle until it answers. Verified on the board with two
      throwaway builds: SDA on an unconnected pin (every SMP `error=no_sensor`, commands still
      answered) and one read in ten forced to fail (`error=read_failed`, re-init next cycle,
      no timing drift)
- [ ] **FW7** (optional, skipped) `GET` command: ACK,CFG already echoes every change

## 3. GUI — `gui_python/`

- [x] **PY1** Reconnection: a disconnect the user did not ask for is retried every 1 s
      ("Cancelar reconexión" stops it); on success the board has rebooted, so the GUI sends
      INIT and then the configuration confirmed before the loss. A baud change restores it
      the same way. Verified on the board by closing the port's fd under the reader
- [x] **PY2** `_on_frame` decodes with `messages.py` before touching any widget; malformed
      frames and unknown types count as rejected
- [x] **PY3** `ConfigPanel`: rate, T/H/P (the last ticked box is locked), average + W,
      peaks + θ (`QDoubleSpinBox`, 0.1 steps, C locale); one Aplicar = one CFG; state
      pending → confirmed / RECHAZADA; "En el ESP32:" shows the echo
- [x] **PY4** `ReadingsPanel`: "Lectura válida" / "LECTURA INVÁLIDA (code)" / "SIN DATOS desde
      hh:mm:ss" (watchdog 2.5 periods), seq, Δt, frames lost from seq gaps
- [x] **PY5** `SensorPlots`: average curve, θ line (with a legend entry) and peak markers on
      T, also while T is hidden; gaps > 3 s break the lines
- [x] **PY6** `PeakPanel`: θ in force + history (ESP32 time, PC time, value, θ), newest first
- [x] **PY7** `CommandBox`: any payload, framed with a valid checksum (BAUD refused there:
      the selector runs the ordered renegotiation)
- [x] **PY8** PC recomputation of the average, labelled "Validación PC (solo verificación)",
      with N and the difference; on the board it matched the ESP32 within 0.0054 °C over 198
      averages (values travel with two decimals)

## 4. Tests

Unit tests (automatic, `pytest`, compiled for the host by `tests/test_firmware_host.py`):

- [x] **UT1** `tests/firmware/test_temp_proc.c`: average vs. a reference at every step for
      W = 5/10/30 s, window edges, start-up, W change on retained samples, buffer overflow at
      5 Hz × 60 s, uint32 clock wrap
- [x] **UT2** peaks: single, plateau, ramp above θ (0 events), max below θ, noisy plateau (the
      bare minimum rule fires > 5 times, ours once), two peaks, no rise, θ at confirmation
- [x] **UT3** `tests/firmware/test_sampler_cfg.c`: round trips, the seven combinations, wrong
      count / order / key, every bad value of every field, nothing written on failure

Mandatory tests (PDF section 6; procedure + result in README, all to be shown in the video):

- [x] **MT1** Real readings on the board (README table)
- [x] **MT2** Seven combinations captured on the board (README)
- [x] **MT3** 1 Hz → 5 Hz → 0.5 Hz with Δt from t_ms (README)
- [x] **MT4** W 5 s → 30 s vs. a reference recomputed from the received T (README)
- [x] **MT5** Unit test (UT2), the PEAK path with a test build (h = 0.02 °C: 14 noise events
      in 40 s), and the real thing on 2026-11-02: θ = 26.1 °C, a fingertip took T from 25.6 to
      33.98 °C, one `PEAK,t_ms=38544,peak_c=33.98` 1 s after the maximum, none during the 30+ s
      cool-down above θ. Repeat it on camera for the video
- [x] **MT6** Only H / H+P selected: average and peaks keep coming (README)
- [x] **MT7** Invalid CFGs rejected naming the field; a real USB unplug on 2026-11-02:
      CONEXIÓN PERDIDA, retries every ~1 s, reconnected 11.5 s later and restored the
      configuration by itself. Repeat both on camera for the video

## 5. Docs and video

- [x] **DOC1** README: installation, wiring, use, protocol, design decisions, screenshots
      (`docs/screenshots/`, taken from the real GUI on the real board), test results
- [ ] **DOC2** Doxygen HTML: `doxygen` is not installed on the v6.1 machine. Run `doxygen` on a
      machine that has it and commit `docs/doxygen/html` (T1 did)
- [x] **VID1** `video_demostracion.mp4` (9:13 min, 97.2 MB, looped background music), re-recorded 2026-11-13:
      a real-time recording of the GUI on the real board with caption banners, covering
      tests 1-7, plus three phone shots of the physical setup: VID_20261113_165609072.mp4
      0:00-0:20 at 4:28 and 0:55-end at 5:44 (touching the sensor), and all of
      VID_20261113_165843273.mp4 at 7:46 (unplugging and replugging the USB cable). Touches
      and the unplug were done live by a team member. Under GitHub's 100 MiB file limit (7.6 MB to spare)
- [x] **VID2** Delivered as a file in the repo root (allowed by PDF section 8), under
      GitHub's 100 MB limit, so no external hosting is needed

---

## Grading (PDF section 7)

| Criterion | Code | Video | Total | Items |
|---|---|---|---|---|
| Real BME688 readings (T, H, P), correct acquisition | 0.35 | 0.65 | 1.00 | FW1, FW2, FW6, MT1 |
| Configurable, verifiable sampling rate | 0.30 | 0.40 | 0.70 | FW2, FW3, PY3, MT3 |
| Variable selection + bidirectional protocol | 0.35 | 0.45 | 0.80 | P1, FW3, PY2, PY3, MT2 |
| Temperature moving average on the ESP32 | 0.40 | 0.40 | 0.80 | FW4, UT1, PY5, MT4 |
| Peak detection and events on the ESP32 | 0.35 | 0.45 | 0.80 | FW5, UT2, PY5, PY6, MT5 |
| GUI: controls, plots and states | 0.15 | 0.65 | 0.80 | PY2–PY6 |
| Robustness, invalid commands, reconnection | 0.25 | 0.45 | 0.70 | FW6, PY1, PY7, UT3, MT7 |
| Modularity, README, test evidence | 0.25 | 0.15 | 0.40 | DOC1, DOC2, UT* |
| **Total** | **2.40** | **3.60** | **6.00** | + 1.0 base = 7.0 |

## Requirements matrix (PDF → where it lives)

| PDF | Requirement | Firmware | GUI |
|---|---|---|---|
| 2.1.1 | Real T (°C), H (%RH), P (hPa) | `bme688_read()` (FW1) | `ReadingsPanel`, `SensorPlots` |
| 2.1.2 | Init/read failures handled, no invented values | `bme688_init()`, FW6 | PY4 |
| 2.1.3 | Common rate 0.5 / 1 / 2 / 5 Hz from the GUI, 1 Hz default | `sampler_cfg_t.period_ms` | PY3 |
| 2.1.4 | Changes without restart; respect the conversion time | FW2 (`vTaskDelayUntil`), FW1 | — |
| 2.2 | T/H/P selectable, 7 combinations, empty rejected | `sampler_valid_vars()`, FW3 | PY3 |
| 2.2 | Only selected variables per packet; T still acquired | FW2 | PY2 |
| 3.1 | Moving average over W (5/10/30/60 s, 10 default), on/off | `temp_proc` FW4 | PY3, PY5 |
| 3.1 | `temp_avg_c` label; incomplete-window flag; W change uses retained samples | FW2, FW4 | PY5 |
| 3.2 | Local max ≥ θ (0.1 °C resolution, 28.0 default), on/off | `temp_proc` FW5 | PY3 |
| 3.2 | Independent event (value, θ, time), not repeated; history in GUI | FW2, FW5 | PY6 |
| 4 | Connection: ports, baud, connect/disconnect, status | `uart_link` (T1) | `ConnectionPanel` (T1) |
| 4 | Show the configuration the ESP32 confirmed | ACK,CFG echo (FW3) | PY3 |
| 4 | Non-blocking GUI; port errors, disconnects, rejected commands | — | `SerialWorker` (T1), PY1 |
| 4 | Embedded computation not replaced by the GUI | FW4, FW5 | PY8 labelled "validación" |
| 5 | Documented protocol: data / commands / acks / errors / events, seq or timestamp | `commands.c`, FW2 | `_on_frame` |
| 5 | Invalid commands answered; no partial configurations | `sampler_set_config()` (atomic) | PY3 |
| 8 | `esp32_firmware/`, `gui_python/`, `requirements.txt`, README, video, optional `tests/` | ✔ layout | ✔ layout |

## Design decisions and traps (T2)

1. **A peak is not a threshold crossing** (spec 3.2, "Distinción conceptual"). A steady ramp
   above θ has no local maximum. UT2 must prove that, and the video should say it.
2. **Sensor noise creates spurious local maxima.** Once T hovers above θ, sample-to-sample
   jitter (measured 0.02 °C rms at T×2, so swings of ±0.05 °C) satisfies the minimum rule
   over and over. The spec allows filtering or a minimum separation
   "siempre que la estrategia se explique y pueda verificarse". Options:
   (a) hysteresis: after an event, re-arm only once T < θ − h;
   (b) minimum time between events;
   (c) confirm a candidate maximum only after T has dropped Δ below it (prominence; adds a
   delay of however long the drop takes).
   (a) or (c), with h or Δ ≈ 0.1–0.2 °C (5–10× the measured noise), is simple to explain and
   to unit-test. Write the
   choice in README and test it in UT2.
3. **Hidden T is still acquired.** `vars` gates transmission only (spec 2.2, test MT6).
4. **Average semantics.** Window `(t − W, t]`; retain 60 s × 5 Hz regardless of the current W
   (`TEMP_AVG_CAPACITY`); report the incomplete window during start-up and right after W
   grows; send the result as `temp_avg_c`.
5. **Atomic configuration** (spec 5). `sampler_set_config()` validates everything first, and
   the GUI only shows what the ACK echoed.
6. **Conversion time vs. the FreeRTOS tick.** ESP-IDF runs `CONFIG_FREERTOS_HZ=100` (10 ms
   tick) and `pdMS_TO_TICKS()` rounds *down*: `vTaskDelay(pdMS_TO_TICKS(43))` waits about
   40 ms, and anything under 10 ms waits 0. A read issued that way lands before the conversion
   ends. Round up (`pdMS_TO_TICKS(x) + 1`), poll the new-data bit, or busy-wait the sub-tick
   rest with `esp_rom_delay_us()`. The sampling periods themselves are whole ticks. Real
   numbers: 42.6 ms predicted, 40.3 ms measured; `vTaskDelay(pdMS_TO_TICKS(42))` is 4 ticks
   and returns after 30–40 ms, i.e. before the conversion ends.
7. **Gas heater off.** It is not required, and heating the hot plate biases T: four 100 ms
   pulses at 300 °C raised the reading by about 0.7 °C, which took ~2 s to fade (measured).
   README cites this as the reason.
8. **I²C API.** Use `driver/i2c_master.h` (component `esp_driver_i2c`), which works on v5.5
   and v6.x. The legacy `driver/i2c.h` is deprecated.
9. **No invented values.** A failed read sends nothing that looks like a measurement. The
   stubs already behave this way end to end.
10. **Time base.** `t_ms` from `esp_timer_get_time()` at measurement time, `seq` per packet.
    Together they are the evidence for MT3.
11. **The GUI never computes graded results** (spec 4). The average and peaks come from the
    ESP32; any PC recomputation is labelled as validation (PY8).
12. **Bandwidth is no longer a constraint.** Worst case is about 125 B per SMP at 5 Hz ≈
    6.3 kbaud (0.7 % of 921600, 5.5 % of 115200). T1's batching and its 921600 justification
    do not apply, but nothing forces a change either.
13. **"Configurar velocidad serial"** (spec 4) is already covered by T1's runtime
    renegotiation, which is also in the GUI.

## Carried over from T1

| T1 piece | In T2 |
|---|---|
| `protocol.[ch]`, `protocol.py` (framing + XOR checksum) | unchanged; plus the host-compiled C test T1 never had |
| `uart_link.[ch]` (driver, RX task, BAUD switch with auto-revert) | unchanged |
| `commands.c` dispatcher, `parse_field()`, `handle_baud()` | unchanged; CFG/ENV replaced, `send_ack()` dropped (T2 ACKs carry data) |
| `SerialWorker` (EN-pulse reset, boot wait, deferred baud switch, port listing) | unchanged |
| `ConnectionPanel` (baud selector = desired link speed, never the opening speed) | unchanged |
| `MainWindow` shell: renegotiation state machine, counters, ACK-driven resets | unchanged; accelerometer/env routing removed |
| `accel_plots.py` → `widgets/sensor_plots.py` | adapted: per-sample push, T/H/P, autoscale, SI prefixes off, "no transmitida" |
| `env_panel.py` → `widgets/readings_panel.py` | adapted: T/H/P, "no transmitida", seq / ESP32 time / Δt |
| Tests: protocol, SerialWorker, renegotiation | unchanged apart from strings; moved to root `tests/` |
| `sdkconfig.defaults`, `.gitignore`, `Doxyfile` | unchanged / renamed |
| `accel_sim`, `env_sim` | dropped: simulated data is forbidden in T2. Their patterns (validated atomic config, snapshot getter, start only on INIT) live on in `sampler.c` |
| `config_panel.py` | replaced by T2's `ConfigPanel` (one CFG per Aplicar); keeps T1's `_combo()` helper |
| Measured reuse (README "Reutilización de la Tarea 1") | protocol.c, uart_link.[ch], sdkconfig.defaults 100 %; serial_worker.py 98 %; connection_panel.py 84 %; commands.c 78 %; main_window.py 45 % |

## Lessons from T1 that apply here

1. **Pulse EN on connect.** Opening the port alone left the CP2102 board hung in most
   connects (1–4 usable out of 10); the esptool-style pulse gave 10/10. It lives in
   `SerialWorker.run()`, and must not move to `open()`.
2. **One meaning per control.** The baud selector is the desired link speed, never the
   opening speed. Making it the opening speed shipped a "Conectado" that received nothing.
3. **Reset GUI state on the ACK, not on send.** Same for T2's confirmed-config display.
4. **Counters stay mutually exclusive.** A valid checksum with malformed fields counts as
   rejected.
5. **Never block in esp_timer callbacks.** Do I/O in tasks. In T2 the BME688 read blocks
   for the conversion, so it belongs in a task.
6. **Config shared across tasks:** validate, then copy under a critical section; readers
   take snapshots.
7. **UART0 carries ESP_LOG too.** `uart_vfs_dev_use_driver()` keeps log lines whole; never
   `printf` a `$` line.
8. **MINIMAL_BUILD is ON:** list every component in PRIV_REQUIRES.
9. **Parse strictly** (`parse_field()`) before any narrowing cast.
10. **GUI rules:** serial I/O only in the QThread, widgets never see the port, redraw from a
    timer and never per sample.
11. **Build the host test harness from day one.** T1 kept `accel_sim_eval()` "host-testable"
    but never tested it; T2 has `tests/test_firmware_host.py`.
12. **The error/robustness work came last in T1 and never got done** (PY1 reconnect, soak
    test, error demo). Here it is worth 0.70 and has its own mandatory test, so schedule it.
13. **Keep README in sync.** T1's README still says the Doxygen HTML is git-ignored when it
    was committed.

## Measured on the real sensor (2026-11-02)

From `../bme688_test` (local to the v6.1 machine, not in this repo; same pins, 100 kHz and
oversampling as this firmware), repeated over several boots with identical results:

| What | Result |
|---|---|
| Module | real BME688 (chip id 0x61, variant 0x01) at **0x76** (SDO low), own SDA/SCL pull-ups |
| `bme68x_init()` (soft reset + calibration) | 17 ms at 100 kHz |
| Forced conversion, T×2 / P×16 / H×1, IIR off | **40.3 ms** measured (polling new_data), 42.6 ms from `bme68x_get_meas_dur()` |
| Indoor values at rest | ~24.3 °C, ~54 %RH, ~952 hPa (Santiago; standard-atmosphere altitude ~520 m) |
| Noise (std dev, 20 back-to-back conversions) | T 0.02 °C, RH 0.01 %RH, P 0.01 hPa |
| Gas heater 300 °C / 100 ms | first pulse after reset never sets heat_stab (status 0xA0), later ones do (0xB0) |
| Heater self-heating | +0.7 °C on T after four pulses, gone in ~2 s |
| Self-heating from sampling (T2 firmware, heater off) | ~+0.1 °C after 100 s at 5 Hz: too little to provoke a peak (h = 0.2 °C) |
| `bme688_init()` retry in the acquisition task | ~165 ms (Bosch init + config poll in 10 ms steps); a 5 Hz cycle that re-inits overruns by ~25 ms, and `xTaskDelayUntil()` keeps the schedule |
| ESP32 average vs. PC reference | ≤ 0.0075 °C over 681 averages (values travel with two decimals) |

## Open questions

- [x] Which BME688 breakout is it: address 0x76 or 0x77, are pull-ups on board, is there a CS pin?
      Answered 2026-11-02: 0x76, pull-ups on the module, I²C works as wired (whether it has a
      CS pin was not recorded)
- [x] W: only {5, 10, 30, 60}, the spec's required values, offered as a combo box
- [x] Peak strategy: hysteresis 0.2 °C (trap 2, option (c) generalised to both directions)
- [x] Sensor-fault reporting format: `SMP,...,error=<code>` (P1)
- [x] Retained average samples are reset only on INIT; rate changes and enable/disable keep
      them (the window is defined in time, so mixed rates are fine)
- [x] Video hosting (VID2): file in the repo root

## Environment notes (2026-11-01, updated 2026-11-02)

The code must build on both machines' IDF versions.

- `~/aur_src` machine: ESP-IDF **v5.5.5** (AUR), activate with
  `. ~/aur_src/esp-idf/export.sh`. Python 3.14 with system PyQt5 5.15.11, numpy 2.5,
  pyserial 3.5 and pytest 9; `.venv/` made with `--system-site-packages`, plus pyqtgraph 0.14.
  T1's firmware builds unchanged on this IDF (checked 2026-11-01)
- Machine with the board: ESP-IDF **v6.1** from the Espressif installer
  (`. ~/.espressif/tools/activate_idf_v6.1.sh`), the version T1 was built with. T2 builds
  with zero warnings (2026-11-02). Python 3.11 with system PyQt5 5.15.9; no pyserial,
  pyqtgraph, pytest or `.venv/` yet
- Board: ESP32 DevKit with a CP2102 bridge, `/dev/ttyUSB0`; the user must be in `dialout`
