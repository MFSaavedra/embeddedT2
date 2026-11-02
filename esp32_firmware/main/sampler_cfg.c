/**
 * @file sampler_cfg.c
 * @brief Defaults, validation, parsing and formatting of the runtime configuration, see
 *        sampler_cfg.h. Pure C: no ESP-IDF includes (tests/firmware/test_sampler_cfg.c).
 */
#include "sampler_cfg.h"
#include "app_config.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>

/** Number of key=value fields in a CFG command. */
#define CFG_FIELDS 6

/** Keys of the CFG fields, in their mandatory order. */
static const char *const KEYS[CFG_FIELDS] = {
    "sampling_hz", "variables", "avg_enabled", "window_s", "peak_enabled", "threshold_c",
};

/** One allowed sampling rate: its text on the wire and its period. */
typedef struct {
    const char *hz;         /**< Rate as written in the CFG command, e.g. "0.5". */
    uint16_t    period_ms;  /**< Sampling period, ms. */
} rate_t;

/** The allowed sampling rates (spec 2.1.3). */
static const rate_t RATES[] = {
    { "0.5", 2000 }, { "1", 1000 }, { "2", 500 }, { "5", 200 },
};

/** The allowed average windows W, s (spec 3.1). */
static const unsigned WINDOWS_S[] = { 5, 10, 30, 60 };

/* ------------------------------ validation ------------------------------ */

/**
 * @brief Find the rate whose period is @p period_ms.
 * @param period_ms  Sampling period, ms.
 * @return The entry of RATES, or NULL if the period is not allowed.
 */
static const rate_t *rate_for_period(unsigned period_ms)
{
    for (size_t i = 0; i < sizeof RATES / sizeof RATES[0]; i++) {
        if (RATES[i].period_ms == period_ms) {
            return &RATES[i];
        }
    }
    return NULL;
}

/**
 * @brief Check that @p seconds is one of WINDOWS_S.
 * @param seconds  Window W, s.
 * @return true if allowed.
 */
static bool valid_window(unsigned seconds)
{
    for (size_t i = 0; i < sizeof WINDOWS_S / sizeof WINDOWS_S[0]; i++) {
        if (WINDOWS_S[i] == seconds) {
            return true;
        }
    }
    return false;
}

sampler_cfg_t sampler_cfg_default(void)
{
    const sampler_cfg_t cfg = {
        .period_ms    = SAMPLER_DEFAULT_PERIOD_MS,
        .vars         = SAMPLER_VAR_ALL,
        .avg_enabled  = AVG_DEFAULT_ENABLED,
        .avg_window_s = AVG_DEFAULT_WINDOW_S,
        .peak_enabled = PEAK_DEFAULT_ENABLED,
        .threshold_dc = PEAK_DEFAULT_THRESHOLD_DC,
    };
    return cfg;
}

bool sampler_cfg_valid(const sampler_cfg_t *cfg)
{
    return cfg != NULL &&
           rate_for_period(cfg->period_ms) != NULL &&
           cfg->vars != 0 && (cfg->vars & ~SAMPLER_VAR_ALL) == 0 &&
           valid_window(cfg->avg_window_s) &&
           cfg->threshold_dc >= PEAK_MIN_THRESHOLD_DC && cfg->threshold_dc <= PEAK_MAX_THRESHOLD_DC;
}

/* -------------------------------- parsing -------------------------------- */

/**
 * @brief Value part of a "key=value" field.
 * @param field  The field.
 * @param key    The key it must have.
 * @return Pointer to the value, or NULL if @p field does not start with "<key>=".
 */
static const char *value_of(const char *field, const char *key)
{
    size_t len = strlen(key);
    return (strncmp(field, key, len) == 0 && field[len] == '=') ? field + len + 1 : NULL;
}

/**
 * @brief "0.5" / "1" / "2" / "5" -> sampling period.
 * @param      v          Value text.
 * @param[out] period_ms  Written on success.
 * @return true if @p v is one of the allowed rates, written exactly as in RATES.
 */
static bool parse_rate(const char *v, uint16_t *period_ms)
{
    for (size_t i = 0; i < sizeof RATES / sizeof RATES[0]; i++) {
        if (strcmp(v, RATES[i].hz) == 0) {
            *period_ms = RATES[i].period_ms;
            return true;
        }
    }
    return false;
}

/**
 * @brief "THP", "PT", ... -> SAMPLER_VAR_* bits.
 * @param      v     Value text: letters T, H, P, each at most once.
 * @param[out] vars  Written on success.
 * @return false for an empty selection, an unknown letter or a repeated one.
 */
static bool parse_vars(const char *v, uint8_t *vars)
{
    uint8_t bits = 0;
    for (; *v != '\0'; v++) {
        uint8_t bit = (*v == 'T') ? SAMPLER_VAR_T : (*v == 'H') ? SAMPLER_VAR_H
                    : (*v == 'P') ? SAMPLER_VAR_P : 0;
        if (bit == 0 || (bits & bit) != 0) {
            return false;
        }
        bits |= bit;
    }
    *vars = bits;
    return bits != 0;
}

/**
 * @brief "0" / "1" -> bool.
 * @param      v     Value text.
 * @param[out] flag  Written on success.
 * @return true for exactly "0" or "1".
 */
static bool parse_flag(const char *v, bool *flag)
{
    if (strcmp(v, "0") != 0 && strcmp(v, "1") != 0) {
        return false;
    }
    *flag = (v[0] == '1');
    return true;
}

/**
 * @brief Window in whole seconds: 1 to 3 digits, nothing else, and one of WINDOWS_S.
 * @param      v        Value text.
 * @param[out] seconds  Written on success.
 * @return true if valid.
 */
static bool parse_window(const char *v, uint8_t *seconds)
{
    unsigned value = 0;
    size_t digits = 0;
    for (; isdigit((unsigned char)*v) && digits < 3; v++, digits++) {
        value = value * 10 + (unsigned)(*v - '0');
    }
    if (digits == 0 || *v != '\0' || !valid_window(value)) {
        return false;
    }
    *seconds = (uint8_t)value;
    return true;
}

/**
 * @brief Threshold with exactly one decimal -> tenths of a degree, without going through float.
 *
 * "28.0" -> 280, "-3.5" -> -35, "-0.5" -> -5. Accepted form: an optional '-', 1 to 3 digits,
 * '.', exactly one digit. "28", "28.05", "+28.0" and "28.0C" are rejected.
 *
 * @param      v             Value text.
 * @param[out] threshold_dc  Written on success.
 * @return true if valid and within the sensor's -40.0 .. 85.0 C range.
 */
static bool parse_threshold(const char *v, int16_t *threshold_dc)
{
    const bool negative = (*v == '-');
    if (negative) {
        v++;
    }
    int tenths = 0;
    size_t digits = 0;
    for (; isdigit((unsigned char)*v) && digits < 3; v++, digits++) {
        tenths = tenths * 10 + (*v - '0');
    }
    if (digits == 0 || v[0] != '.' || !isdigit((unsigned char)v[1]) || v[2] != '\0') {
        return false;
    }
    tenths = tenths * 10 + (v[1] - '0');
    if (negative) {
        tenths = -tenths;
    }
    if (tenths < PEAK_MIN_THRESHOLD_DC || tenths > PEAK_MAX_THRESHOLD_DC) {
        return false;
    }
    *threshold_dc = (int16_t)tenths;
    return true;
}

bool sampler_cfg_parse(char *const fields[], int n, sampler_cfg_t *out, const char **bad_key)
{
    if (n != CFG_FIELDS) {
        *bad_key = "fields";
        return false;
    }
    const char *v[CFG_FIELDS];
    for (int i = 0; i < CFG_FIELDS; i++) {
        v[i] = value_of(fields[i], KEYS[i]);
        if (v[i] == NULL) {                     /* missing, misspelt or out of order */
            *bad_key = KEYS[i];
            return false;
        }
    }

    sampler_cfg_t cfg;
    const char *bad = NULL;
    if (!parse_rate(v[0], &cfg.period_ms)) {
        bad = KEYS[0];
    } else if (!parse_vars(v[1], &cfg.vars)) {
        bad = KEYS[1];
    } else if (!parse_flag(v[2], &cfg.avg_enabled)) {
        bad = KEYS[2];
    } else if (!parse_window(v[3], &cfg.avg_window_s)) {
        bad = KEYS[3];
    } else if (!parse_flag(v[4], &cfg.peak_enabled)) {
        bad = KEYS[4];
    } else if (!parse_threshold(v[5], &cfg.threshold_dc)) {
        bad = KEYS[5];
    }
    if (bad != NULL) {
        *bad_key = bad;
        return false;
    }
    *out = cfg;
    return true;
}

/* ------------------------------- formatting ------------------------------- */

int sampler_cfg_format(const sampler_cfg_t *cfg, char *buf, size_t size)
{
    const rate_t *rate = rate_for_period(cfg->period_ms);
    const int t = cfg->threshold_dc < 0 ? -cfg->threshold_dc : cfg->threshold_dc;
    return snprintf(buf, size,
                    "sampling_hz=%s,variables=%s%s%s,avg_enabled=%d,window_s=%u,"
                    "peak_enabled=%d,threshold_c=%s%d.%d",
                    rate != NULL ? rate->hz : "?",
                    (cfg->vars & SAMPLER_VAR_T) ? "T" : "",
                    (cfg->vars & SAMPLER_VAR_H) ? "H" : "",
                    (cfg->vars & SAMPLER_VAR_P) ? "P" : "",
                    (int)cfg->avg_enabled, (unsigned)cfg->avg_window_s, (int)cfg->peak_enabled,
                    cfg->threshold_dc < 0 ? "-" : "", t / 10, t % 10);
}
