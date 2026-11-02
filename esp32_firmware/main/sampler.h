/**
 * @file sampler.h
 * @brief Periodic acquisition: reads the BME688, feeds temp_proc and emits SMP / PEAK frames
 *        carrying only the selected variables (spec 2.1, 2.2, 3).
 *
 * The whole runtime configuration is one struct, applied atomically by sampler_set_config():
 * every field is validated before anything changes, so a rejected CFG leaves the previous
 * configuration intact (spec 5: no partially applied configuration). This is T1's
 * accel_sim_set_axis() pattern: the configuration is written by the UART RX task and read by
 * the acquisition task, so it is only touched inside a critical section and read as a
 * snapshot (sampler_get_config()).
 *
 * Scaffold status: configuration storage and validation work; the acquisition task is
 * TODO(FW2), so sampler_start() only flips a flag.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/**
 * @name Variable selection bits (sampler_cfg_t::vars)
 * @{
 */
#define SAMPLER_VAR_T   0x01u   /**< Temperature is transmitted. */
#define SAMPLER_VAR_H   0x02u   /**< Relative humidity is transmitted. */
#define SAMPLER_VAR_P   0x04u   /**< Pressure is transmitted. */
#define SAMPLER_VAR_ALL (SAMPLER_VAR_T | SAMPLER_VAR_H | SAMPLER_VAR_P)  /**< All three. */
/** @} */

/** Complete runtime configuration, applied as a whole or not at all. */
typedef struct {
    uint16_t period_ms;     /**< Sampling period: 2000, 1000, 500 or 200 ms (0.5 / 1 / 2 / 5 Hz). */
    uint8_t  vars;          /**< SAMPLER_VAR_* bits to transmit, never 0 (spec 2.2). Gates
                                 transmission only: T is always acquired for the processing. */
    bool     avg_enabled;   /**< Moving average of T on/off (spec 3.1). */
    uint8_t  avg_window_s;  /**< Average window W: 5, 10, 30 or 60 s. */
    bool     peak_enabled;  /**< Peak detection on/off (spec 3.2). */
    int16_t  threshold_dc;  /**< Peak threshold in tenths of a degree C (280 = 28.0 C). */
} sampler_cfg_t;

/**
 * @brief Load the defaults. TODO(FW2): also create the acquisition task.
 *
 * Does not start acquiring: that is sampler_start(), called by the INIT command. Call once
 * from app_main(), after uart_link_init() and bme688_init().
 */
void sampler_init(void);

/** @brief Start periodic acquisition at the configured rate. No-op if already running. */
void sampler_start(void);

/** @brief Stop periodic acquisition (used by INIT and BAUD). No-op if not running. */
void sampler_stop(void);

/** @brief Restore every field to its app_config.h default. Takes effect at once. */
void sampler_reset_defaults(void);

/**
 * @brief Check that @p ms is an allowed sampling period.
 * @param ms  Period in milliseconds.
 * @return true for 2000, 1000, 500 or 200.
 */
bool sampler_valid_period(unsigned ms);

/**
 * @brief Check that @p vars is a non-empty selection of known variables.
 * @param vars  SAMPLER_VAR_* bits.
 * @return true for any of the seven non-empty combinations of T, H and P.
 */
bool sampler_valid_vars(unsigned vars);

/**
 * @brief Check that @p seconds is an allowed average window.
 * @param seconds  Window W in seconds.
 * @return true for 5, 10, 30 or 60.
 */
bool sampler_valid_window(unsigned seconds);

/**
 * @brief Check that @p threshold_dc is within the sensor's operating range.
 * @param threshold_dc  Threshold in tenths of a degree C.
 * @return true for -40.0 .. 85.0 C.
 */
bool sampler_valid_threshold(int threshold_dc);

/**
 * @brief Validate every field of @p cfg.
 * @param[in] cfg  Candidate configuration (NULL is invalid).
 * @return true if all four sampler_valid_*() checks pass.
 */
bool sampler_valid_config(const sampler_cfg_t *cfg);

/**
 * @brief Replace the whole configuration atomically.
 *
 * @param[in] cfg  New configuration.
 * @return true if applied; false if any field is invalid (nothing changed).
 *
 * @note Thread-safe: the copy happens inside a critical section.
 */
bool sampler_set_config(const sampler_cfg_t *cfg);

/**
 * @brief Snapshot of the current configuration, read inside a critical section.
 * @return Copy of the configuration in force.
 */
sampler_cfg_t sampler_get_config(void);
