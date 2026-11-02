/**
 * @file bme688.h
 * @brief BME688 temperature / relative humidity / pressure over I2C (spec 2.1).
 *
 * Built on the Bosch BME68x SensorAPI (components/bme68x). One forced-mode conversion per
 * bme688_read(), with oversampling T x2 / P x16 / H x1 and the IIR filter off: 42.6 ms
 * predicted by the API, 40.3 ms measured on the team's board.
 *
 * The gas heater is never enabled: the spec leaves gas out, and heating the hot plate would
 * also bias the temperature that the on-device processing works on. Measured on the team's
 * board: four 100 ms pulses at 300 C raise the temperature reading by about 0.7 C.
 *
 * Not thread-safe. app_main() calls bme688_init() once before any task exists; after that,
 * only the acquisition task (sampler.c) calls into this module, retries included.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

/** One compensated measurement; only ever produced from a completed conversion. */
typedef struct {
    float temperature_c;   /**< Temperature, degrees C. */
    float humidity_pct;    /**< Relative humidity, %RH. */
    float pressure_hpa;    /**< Pressure, hPa (the sensor reports Pa: divided by 100). */
} bme688_reading_t;

/**
 * @brief Find the sensor and configure it for T/H/P measurements.
 *
 * Creates the I2C master bus on the first call, probes BME688_ADDR_PRIMARY then
 * BME688_ADDR_SECONDARY, and lets the Bosch API soft-reset the chip, check its chip id
 * (0x61) and read its calibration. Then sets the oversampling, the filter and the heater off.
 * May be called again after a failure (the acquisition task does, see sampler.c).
 *
 * @return ESP_OK if the sensor is ready;
 *         ESP_ERR_NOT_FOUND if nothing acknowledged either address (wiring, SDO, power);
 *         ESP_ERR_TIMEOUT if the bus itself is stuck (typically missing pull-ups);
 *         ESP_ERR_INVALID_RESPONSE if the device is not a BME68x;
 *         ESP_FAIL if the Bosch API reported another error; other codes from the I2C driver.
 */
esp_err_t bme688_init(void);

/**
 * @brief Whether the sensor is ready to measure.
 * @return true after a successful bme688_init(), false again after a failed bme688_read().
 */
bool bme688_is_ready(void);

/**
 * @brief Run one forced-mode T/H/P conversion and return the compensated values.
 *
 * Starts the conversion, waits the time the Bosch API predicts for it (rounded up to whole
 * FreeRTOS ticks, see bme688.c) and reads the result, which the API only accepts if the
 * sensor flags it as new data. Blocks for about 50 ms, so it must be called from a task.
 *
 * A failure, or values outside the sensor's operating range, marks the sensor as not ready,
 * so that the caller re-initialises it before the next read.
 *
 * @param[out] out  Written only on success.
 * @return ESP_OK with @p out filled; ESP_ERR_INVALID_STATE if the sensor is not ready;
 *         ESP_ERR_INVALID_RESPONSE for implausible values; ESP_FAIL otherwise.
 */
esp_err_t bme688_read(bme688_reading_t *out);
