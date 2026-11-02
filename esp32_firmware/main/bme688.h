/**
 * @file bme688.h
 * @brief BME688 temperature / relative humidity / pressure over I2C (spec 2.1).
 *
 * The gas heater is never enabled: the spec leaves gas out, and heating the hot plate would
 * also bias the temperature that the on-device processing works on. Measured on the team's
 * board: four 100 ms pulses at 300 C raise the temperature reading by about 0.7 C.
 *
 * Scaffold status: bme688_init() brings up the I2C bus, finds the sensor at 0x76 or 0x77 and
 * checks its chip id, so the wiring can be verified on the very first flash (`idf.py
 * monitor`). bme688_read() is TODO(FW1) and fails until the measurement path exists; the rest
 * of the firmware must treat that like any other read error and never send a value that was
 * not measured (spec 2.1.2).
 *
 * Not thread-safe. app_main() calls bme688_init() once before any task exists; after that,
 * only the acquisition task (sampler.c) may call into this module, retries included (FW6).
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

/** One compensated measurement; only ever produced from a completed conversion. */
typedef struct {
    float temperature_c;   /**< Temperature, degrees C. */
    float humidity_pct;    /**< Relative humidity, %RH. */
    float pressure_hpa;    /**< Pressure, hPa (the sensor reports Pa: divide by 100). */
} bme688_reading_t;

/**
 * @brief Create the I2C master bus, locate the sensor and check its identity.
 *
 * Probes BME688_ADDR_PRIMARY, then BME688_ADDR_SECONDARY, and reads the chip id (register
 * 0xD0, 0x61 on BME680/BME688) and the variant id (0xF0: 0x01 = BME688, 0x00 = BME680).
 * May be called again after a failure, e.g. once the wiring is fixed: the bus is created on
 * the first call and reused.
 *
 * @return ESP_OK if the sensor answered with the right chip id;
 *         ESP_ERR_NOT_FOUND if nothing acknowledged either address (wiring, SDO, power);
 *         ESP_ERR_TIMEOUT if the bus itself is stuck (typically missing pull-ups);
 *         ESP_ERR_INVALID_RESPONSE if the device is not a BME68x;
 *         any other code comes from the I2C driver.
 */
esp_err_t bme688_init(void);

/**
 * @brief Whether bme688_init() has found and identified the sensor.
 * @return true after a successful bme688_init().
 */
bool bme688_is_ready(void);

/**
 * @brief I2C address the sensor answered at.
 * @return 0x76 or 0x77, or 0 if the sensor has not been found.
 */
uint8_t bme688_address(void);

/**
 * @brief Run one forced-mode T/H/P conversion and return the compensated values.
 *
 * Blocks for the conversion time (tens of ms, set by the oversampling), so it must be called
 * from the acquisition task, never from an esp_timer callback.
 *
 * @param[out] out  Written only on success.
 * @return ESP_OK with @p out filled; ESP_ERR_INVALID_STATE if the sensor was not found;
 *         ESP_ERR_NOT_SUPPORTED until TODO(FW1) is done; I2C errors otherwise.
 */
esp_err_t bme688_read(bme688_reading_t *out);
