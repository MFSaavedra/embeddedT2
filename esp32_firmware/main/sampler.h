/**
 * @file sampler.h
 * @brief Periodic acquisition: reads the BME688 at the configured rate, feeds every
 *        temperature to temp_proc and sends one SMP frame per reading with only the selected
 *        variables, plus a PEAK frame for each detected peak (spec 2.1, 2.2, 3).
 *
 * Frames (README.md "Protocolo"):
 *
 *     SMP,seq=<n>,t_ms=<ms>[,temperature_c=..][,humidity_pct=..][,pressure_hpa=..]
 *        [,temp_avg_c=..,avg_n=..,avg_window_complete=<0|1>]
 *     SMP,seq=<n>,t_ms=<ms>,error=<no_sensor|read_failed>
 *     PEAK,t_ms=<ms>,peak_c=..,threshold_c=..
 *
 * The configuration (sampler_cfg.h) is written by the UART RX task (CFG, INIT) and read by the
 * acquisition task. One mutex guards it together with the acquisition state, and the
 * acquisition task holds that mutex for a whole cycle (read, process, send). So a new
 * configuration always applies between two readings, never in the middle of one, and once
 * sampler_stop() returns no acquisition frame is pending (BAUD relies on that).
 */
#pragma once

#include <stdbool.h>

#include "sampler_cfg.h"

/**
 * @brief Load the defaults and create the acquisition task (idle until sampler_start()).
 *
 * Call once from app_main(), after uart_link_init() and bme688_init().
 */
void sampler_init(void);

/**
 * @brief Start periodic acquisition, from a clean state: sequence number 0, no retained
 *        average samples, peak detector reset. Called by INIT.
 */
void sampler_start(void);

/**
 * @brief Stop periodic acquisition (used by INIT and BAUD).
 *
 * Waits for a reading in progress to finish, so nothing is sent after it returns.
 */
void sampler_stop(void);

/** @brief Restore every field to its app_config.h default. Takes effect at the next reading. */
void sampler_reset_defaults(void);

/**
 * @brief Replace the whole configuration atomically.
 * @param[in] cfg  New configuration.
 * @return true if applied; false if any field is invalid (nothing changed).
 */
bool sampler_set_config(const sampler_cfg_t *cfg);

/**
 * @brief Copy of the configuration in force.
 * @return The current configuration.
 */
sampler_cfg_t sampler_get_config(void);
