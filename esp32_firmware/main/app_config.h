/**
 * @file app_config.h
 * @brief Compile-time constants and spec defaults for the Tarea 2 firmware.
 *
 * Runtime-configurable values (sampling rate, transmitted variables, average window,
 * peak threshold) live in sampler.c; only their *defaults* and allowed sets are defined
 * here. Every default has a twin in the GUI that must be changed with it (see CLAUDE.md,
 * "Paired constants").
 */
#pragma once

#include "driver/uart.h"

/** Firmware version, reported in the reply to INIT (`ACK,INIT,2.0`) so the GUI can display it. */
#define FW_VERSION "2.0"

/**
 * @name Serial link (carried over from Tarea 1)
 * @{
 */
#define LINK_UART_NUM       UART_NUM_0  /**< USB-serial bridge on the dev board (shared with the console). */
#define LINK_BAUD           921600      /**< Boot speed of the link, must equal DEFAULT_BAUD in the GUI and
                                         *   CONFIG_ESP_CONSOLE_UART_BAUDRATE. T2 traffic is tiny (5 Hz x
                                         *   ~120 B < 1 kB/s), so any rate works; 921600 is kept because it
                                         *   is the configuration T1 validated on this board. */
#define LINK_RX_BUF_SIZE    1024        /**< Driver RX ring buffer, bytes. */
#define LINK_TX_BUF_SIZE    4096        /**< Driver TX ring buffer, bytes (frames are copied into it). */
#define LINK_MAX_LINE       256         /**< Longest accepted command line (PC -> ESP32), bytes. T1 used 128;
                                         *   a key=value CFG with every field is already ~100 bytes. */
#define LINK_MAX_FRAME      512         /**< Longest frame we build (ESP32 -> PC), incl. '$', checksum and newline. */
#define LINK_BAUD_REVERT_MS 5000        /**< After a BAUD switch, revert to LINK_BAUD unless a valid frame
                                         *   arrives within this time: a rate the PC cannot actually drive
                                         *   would otherwise mute the board until someone presses EN.
                                         *   The GUI's own fallback (BAUD_NEGOTIATION_MS) must be longer. */
/** @} */

/**
 * @name BME688 on I2C
 * GPIO21/GPIO22 are the conventional ESP32 DevKit I2C pins: free on the board, not strapping
 * pins (0, 2, 5, 12, 15), not flash pins (6-11) and not input-only (34-39). The wiring table
 * in README.md ("Conexión física") must match these values.
 *
 * Verified on the team's module (2026-11-02, ../bme688_test): a real BME688 (chip id 0x61,
 * variant 0x01) at 0x76, with its own SDA/SCL pull-ups.
 * @{
 */
#define BME688_I2C_PORT     I2C_NUM_0   /**< I2C controller used for the sensor. */
#define BME688_SDA_GPIO     21          /**< SDA pin. */
#define BME688_SCL_GPIO     22          /**< SCL pin. */
#define BME688_I2C_HZ       100000      /**< SCL clock; the BME688 supports up to 3.4 MHz, 100 kHz is the safe start. */
#define BME688_ADDR_PRIMARY   0x76      /**< SDO tied to GND: the team's module. Probed first. */
#define BME688_ADDR_SECONDARY 0x77      /**< SDO tied to VDDIO (e.g. Adafruit). Probed if the first is absent. */
#define BME688_I2C_TIMEOUT_MS 50        /**< Per-transaction timeout. */
/** @} */

/**
 * @name Acquisition (spec 2.1)
 * Rates are handled as periods in ms internally: every period is a whole number of 10 ms
 * FreeRTOS ticks (CONFIG_FREERTOS_HZ = 100), so vTaskDelayUntil() keeps them exact.
 * @{
 */
#define SAMPLER_DEFAULT_PERIOD_MS 1000  /**< Spec: 1 Hz suggested initial value. Allowed: 2000, 1000, 500, 200 (0.5/1/2/5 Hz). */
#define SAMPLER_MIN_PERIOD_MS     200   /**< Fastest allowed rate (5 Hz): one forced-mode T/H/P conversion must fit in
                                         *   it. Measured 40.3 ms with T x2 / P x16 / H x1 (42.6 ms predicted by
                                         *   bme68x_get_meas_dur()), so it fits with room to spare. */
/** @} */

/**
 * @name Local processing (spec 3)
 * @{
 */
#define AVG_DEFAULT_ENABLED     false   /**< Moving average off until the GUI enables it. */
#define AVG_DEFAULT_WINDOW_S    10      /**< Spec: 10 s suggested initial value. Required: 5, 10, 30, 60 s. */
#define AVG_MAX_WINDOW_S        60      /**< Longest window; sizes the retained-sample buffer (temp_proc.h). */
#define PEAK_DEFAULT_ENABLED    false   /**< Peak detection off until the GUI enables it. */
#define PEAK_DEFAULT_THRESHOLD_DC 280   /**< Spec: 28.0 C suggested initial value, in tenths of a degree (0.1 C resolution). */
#define PEAK_MIN_THRESHOLD_DC   (-400)  /**< -40.0 C: bottom of the BME688 operating range. */
#define PEAK_MAX_THRESHOLD_DC   850     /**< 85.0 C: top of the BME688 operating range. */
/** @} */
