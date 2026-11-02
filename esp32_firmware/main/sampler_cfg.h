/**
 * @file sampler_cfg.h
 * @brief The runtime configuration (spec 2.1, 2.2, 3): its fields, defaults, validation, and
 *        its text form in the CFG command and in the ACK that echoes it.
 *
 * Wire form (README.md "Protocolo"): six key=value fields, always all six and in this order:
 *
 *     sampling_hz=<0.5|1|2|5>,variables=<T|H|P|TH|TP|HP|THP>,avg_enabled=<0|1>,
 *     window_s=<5|10|30|60>,peak_enabled=<0|1>,threshold_c=<-40.0..85.0, one decimal>
 *
 * The variables are letters T, H and P in any order, each at most once. An empty selection
 * is invalid (spec 2.2).
 *
 * Pure C with no ESP-IDF dependency, so tests/firmware/test_sampler_cfg.c runs it on the PC.
 * The live copy of the configuration, and the lock that protects it, are in sampler.c.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
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
 * @brief The spec defaults from app_config.h: 1 Hz, T/H/P, average off with W = 10 s, peaks
 *        off with a 28.0 C threshold.
 * @return The default configuration.
 */
sampler_cfg_t sampler_cfg_default(void);

/**
 * @brief Check every field against its allowed values.
 * @param[in] cfg  Candidate configuration (NULL is invalid).
 * @return true if all fields are allowed.
 */
bool sampler_cfg_valid(const sampler_cfg_t *cfg);

/**
 * @brief Parse the six key=value fields of a CFG command.
 *
 * Strict: exactly six fields, in the order of the file header, each with an allowed value.
 * Nothing is written to @p out unless every field is valid, so a bad command can never leave
 * a half-applied configuration behind (spec 5).
 *
 * @param[in]  fields   The fields that follow "CFG", as split by proto_split().
 * @param      n        Number of entries in @p fields.
 * @param[out] out      The parsed configuration, written only on success.
 * @param[out] bad_key  On failure, the key of the first invalid field (or "fields" if there are
 *                      not exactly six), for the ERR reply. Untouched on success.
 * @return true if the six fields are valid.
 */
bool sampler_cfg_parse(char *const fields[], int n, sampler_cfg_t *out, const char **bad_key);

/**
 * @brief Write @p cfg in the wire form of the file header (used to echo it in ACK,CFG).
 * @param[in]  cfg   A valid configuration.
 * @param[out] buf   Destination, NUL-terminated.
 * @param      size  Capacity of @p buf.
 * @return What snprintf() returns: the length of the text, which was truncated if >= @p size.
 */
int sampler_cfg_format(const sampler_cfg_t *cfg, char *buf, size_t size);
