# TODO — Tarea 2 CC5328 (BME688 → ESP32 → PyQt)

**Deadline: Friday 6 November 2026, 23:59.** Deliver a Git repo link or ZIP, with README and
the demo video (file or link). Grading: **code review 40 % (2.4 pts) + demo video 60 %
(3.6 pts)**, scale 1.0–7.0 (base 1.0 + up to 6.0). There is **no live demo**: grading is done
from the 8–12 min video, so every point has to be *visible* in it. Build for the recording.

Item IDs (`P1`, `FW2`, `PY4`, `UT1`, `MT3`, …) match the `TODO(<id>)` comments in the code:
`grep -rn "TODO(" esp32_firmware/main gui_python tests` lists exactly what is left.

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
- [x] BME688 breakout wired as in README "Conexión física"; every boot logs
      `bme688: BME688 found at 0x76 (chip id 0x61, variant 0x01)` (2026-11-02). The local
      `../bme688_test` bring-up test passes all its checks (see "Measured on the real sensor")

## 1. Protocol — do this first, both sides depend on it

- [ ] **P1** Confirm the framing. Recommendation: **keep T1's `$payload*XX`**. It is implemented
      and tested on both sides (now also as host-compiled C), checksummed, and needs no JSON
      parser on the ESP32; the PDF explicitly allows "texto delimitado". JSON Lines is only the
      PDF's *example*. Switching would cost a JSON parser on the ESP32 and a rewrite of
      `protocol.[ch]`/`protocol.py` and their tests. cJSON is bundled as the `json` component
      in IDF v5.5 but, as far as we know, moved to the component registry in v6.x, so check
      that before relying on it
- [ ] **P1** Freeze the fields of the README DRAFT: CFG (complete, atomic), the ACK,CFG echo,
      SMP (seq + t_ms + only the selected variables + `temp_avg_c` / `avg_window_complete`),
      PEAK, error codes. The DRAFT uses key=value fields because the variable set changes per
      packet and the PDF asks for the average to be "etiquetado como `temp_avg_c`"
- [ ] **P1** Decide how a sensor fault reaches the GUI. The boot-time `bme688_init()` failure
      happens while the GUI is still discarding boot output (it resets the board on connect),
      so the acquisition must report it. DRAFT: `SMP,seq,t_ms,error=<code>` with no values.
      Keep `ERR` for command replies only, because the GUI aborts a pending baud
      renegotiation on any ERR
- [ ] **P1** Update README "Protocolo", both interpreters (`commands.c`,
      `main_window.py::_on_frame`) and the tests together

## 2. Firmware — `esp32_firmware/main/`

- [ ] **FW1** BME688 measurement path (`bme688.c`). Recommended: Bosch **BME68x SensorAPI**
      (github.com/boschsensortec/BME68x_SensorAPI, BSD-3-Clause; the PDF allows it)
  - vendor `bme68x.c/.h`, `bme68x_defs.h` + LICENSE as `esp32_firmware/components/bme68x/`
    with `idf_component_register(SRCS "bme68x.c" INCLUDE_DIRS ".")`, and add `bme68x` to
    `main/CMakeLists.txt` PRIV_REQUIRES (MINIMAL_BUILD: unlisted components are not built).
    On the v6.1 machine, `../bme688_test/components/bme68x` is exactly that (v4.4.8, commit
    80ea120, unmodified) and is proven on this board: copy it
  - glue: read → the existing `read_regs()`; write → `[reg, data…]` in one transaction
    (`i2c_master_multi_buffer_transmit()` avoids a copy; `bme68x_set_regs()` already
    interleaves reg/data pairs into that buffer); delay_us → see trap 6 (FreeRTOS tick).
    `../bme688_test/main/main.c` has all three callbacks, working
  - forced mode, heater **disabled**, oversampling e.g. T×2 / P×16 / H×1 (the setting of
    Bosch's `bme68x_selftest_check()`; their forced-mode example uses T×2 / P×1 / H×16), IIR
    filter off or small (a filter delays and flattens the peaks FW5 must detect, so justify the
    choice in README)
  - wait `bme68x_get_meas_dur()` (not rounded down), then check `BME68X_NEW_DATA_MSK` before
    trusting the sample; document the measured conversion time (spec 2.1.4: "respetar el
    tiempo necesario"). T×2 / P×16 / H×1 measured 40.3 ms against 42.6 ms predicted, so the
    prediction is already an upper bound. `bme68x_get_data()` re-polls new_data itself (up to
    5 × 10 ms) before giving up with `BME68X_W_NO_NEW_DATA`, so an early read blocks longer
    instead of returning stale data
  - float output (Bosch default) gives °C, Pa and %RH: divide pressure by 100 to get hPa
- [ ] **FW2** Acquisition task (`sampler.c`, see the comment in `sampler_init()`)
  - task priority below `uart_rx` (10), ≥ 4 KB stack, paced by `vTaskDelayUntil()` with the
    period **re-read every cycle**, so a rate change applies without a restart (spec 2.1.4)
  - `t_ms = esp_timer_get_time() / 1000` taken at the measurement; `seq` +1 per packet, error
    packets included (then a seq gap means a lost frame, not a failed read)
  - T always goes into temp_proc, whatever `vars` says (spec 2.2, "Importante")
  - SMP with only the selected variables, plus `temp_avg_c` and `avg_window_complete` when the
    average is enabled; a detected peak goes out as its own PEAK frame
  - reset temp_proc on INIT; `sampler_stop()` must never leave half a frame queued (BAUD
    drains the TX buffer right after it)
- [ ] **FW3** CFG (`commands.c`, see `handle_cfg()`)
  - all six keys exactly once, strict formats: a table for `sampling_hz`, letters T/H/P without
    repeats for `variables`, `parse_field()` for the integers, exactly one decimal for
    `threshold_c` (convert to tenths without going through float)
  - one `sampler_set_config()`; reply `ACK,CFG,<applied config>`; on failure
    `ERR,BADARG[,<key>]` and nothing changes
  - put the field parsing in a pure-C file (no ESP-IDF includes) so UT3 can run it on the host
  - an empty selection is rejected here **and** prevented in the GUI (spec 2.2: "rechazarse o
    impedirse")
- [ ] **FW4** Moving average (`temp_proc.c`), semantics in `temp_proc.h`: window
      `(t − W, t]`, retention independent of W (a longer W uses samples already held),
      `window_complete` reported during start-up, computed even while T is hidden
- [ ] **FW5** Peak detector (`temp_proc.c`): the minimum rule `T[k−1] > T[k−2]`,
      `T[k−1] ≥ T[k]`, `T[k−1] ≥ θ`, **plus** a spurious-detection strategy (trap 2), one event
      per peak with value, θ in force and the peak's own timestamp
- [ ] **FW6** Sensor faults: retry `bme688_init()` from the acquisition task (the sensor's only
      user after boot), report failed reads with the error form of SMP, recover on its own,
      never send invented values (spec 2.1.2)
- [ ] **FW7** (optional) `GET` command that replies with the current configuration

## 3. GUI — `gui_python/`

- [ ] **PY1** Robustness and reconnection. This was T1's unfinished PY1 and is graded now
      (0.70 pts, test MT7). Tell a pulled cable apart from the user's Desconectar, refresh the
      port list, offer or attempt a reconnect. A reconnect resets the board (EN pulse), so the
      firmware is back on defaults: after `ACK,INIT`, re-send the GUI's configuration with CFG,
      or visibly reset the panels
- [ ] **PY2** `_on_frame`: SMP → `ReadingsPanel.update_sample()` + `SensorPlots.push()` per
      variable present + average display; PEAK → event list. Malformed fields move the frame
      from the OK counter to the rejected one (T1 rule)
- [ ] **PY3** Acquisition panel (rate 0.5/1/2/5 Hz; T/H/P checkboxes that cannot all be off)
      and processing panel (average on/off + W 5/10/30/60; peaks on/off + θ `QDoubleSpinBox`
      with step 0.1 and one decimal, 28.0 by default). One **Aplicar** button sends a single
      CFG and the panel stays "pendiente" until the ACK echo arrives; a "Configuración
      confirmada por el ESP32" block shows that echo (spec 4). On ERR, show the rejection and
      keep the last confirmed config. Defaults mirror `app_config.h`
- [ ] **PY4** Reading states: "sin datos" after ~2.5 periods without an SMP, "lectura
      inválida" for error SMPs, lost-packet count from seq gaps
- [ ] **PY5** Plots: overlay `temp_avg_c` on the temperature plot, mark PEAK events and draw
      the θ line (`pg.InfiniteLine`); deselected variables are already marked
      (`set_transmitted()`)
- [ ] **PY6** Peak history table: ESP32 time, local time, value, θ applied; current θ visible
- [ ] **PY7** Manual command box (raw payload, or a raw line without a checksum). The GUI's own
      controls cannot produce an invalid CFG, but MT7 must show one being rejected
- [ ] **PY8** (optional) PC-side recomputation of the average from received T samples, labelled
      "solo validación (PC)" as spec 4 requires; only possible while T is transmitted

## 4. Tests

Unit tests (automatic, `pytest`, compiled for the host by `tests/test_firmware_host.py`):

- [ ] **UT1** `tests/firmware/test_temp_proc.c`, average: known series vs a reference mean;
      window boundary (`t − W` excluded, `t` included); W change reusing retained samples;
      start-up incomplete window; T hidden makes no difference
- [ ] **UT2** peaks: clean single peak → 1 event; plateau → 1 event; monotonic ramp above θ →
      0 events (exceeding θ is not a peak); local max below θ → 0; noise above θ → handled by
      the chosen strategy
- [ ] **UT3** CFG parsing (pure-C part of FW3): every invalid form (missing or repeated key,
      bad rate, empty or unknown variable, two decimals, out of range) is rejected with no
      partial change

Mandatory tests (PDF section 6; procedure + result in README, all shown in the video):

- [ ] **MT1** Real readings: T, H and P together, with units, wiring and the rate in use
- [ ] **MT2** Seven combinations: at least 3 on video (one, two and three variables); all 7
      documented in README (the SMP seen for each)
- [ ] **MT3** Dynamic rate: 1 Hz → 5 Hz without a restart; periodicity checked from t_ms / seq
      (the readings panel shows Δt)
- [ ] **MT4** Average: W 5 s → 30 s; results compared against a reference calculation; shown
      to be emitted by the ESP32
- [ ] **MT5** Peaks: set θ near ambient, provoke one local maximum gently (finger, breath, warm
      air; stay within the sensor specs), verify exactly one event
- [ ] **MT6** Hidden T: only H and/or P selected, average and peak events still arrive
- [ ] **MT7** Errors: an invalid configuration (PY7) and a serial disconnect/reconnect (PY1)

## 5. Docs and video

- [ ] **DOC1** README: installation (ESP32 + PC), wiring and pins, running, exact packet
      formats, design decisions, screenshots in `docs/screenshots/`, test procedures and
      results, video link
- [ ] **DOC2** Regenerate Doxygen (`doxygen` → `docs/doxygen/html`) and commit it once the code
      settles (T1 committed its HTML)
- [ ] **VID1** Script the 8–12 min video: wiring close-up → connect → MT1 … MT7 → wrap-up. It
      needs voice or clear captions, legible GUI text (record at native resolution, enlarge
      fonts if needed), and the real BME688–ESP32 setup on camera. Cuts are fine; slides or
      screenshots instead of the running system are not
- [ ] **VID2** Hosting: T1's video was 18 MB, but 10 minutes will likely exceed GitHub's 100 MB
      file limit. Upload it (YouTube unlisted, or Drive "anyone with the link"), put the
      **direct link** in README, and check it opens without logging in. It must stay up until
      grading ends. A small enough `video_demostracion.mp4` in the repo is also accepted

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
| `accel_sim`, `env_sim`, `config_panel` | dropped: simulated data is forbidden in T2. Their patterns (validated atomic config, snapshot getter, start only on INIT) live on in `sampler.c` |

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

## Open questions

- [x] Which BME688 breakout is it: address 0x76 or 0x77, are pull-ups on board, is there a CS pin?
      Answered 2026-11-02: 0x76, pull-ups on the module, I²C works as wired (whether it has a
      CS pin was not recorded)
- [ ] W: only {5, 10, 30, 60} (current validation), or any 1–60 s? The spec calls those the
      "valores mínimos requeridos"
- [ ] Peak strategy and its parameter (trap 2)
- [ ] Sensor-fault reporting format (P1)
- [ ] Reset the retained average samples on a rate change, or on average disable/enable?
      Suggestion: only on INIT
- [ ] Video hosting (VID2)

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
