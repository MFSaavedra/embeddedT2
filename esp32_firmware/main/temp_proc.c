/**
 * @file temp_proc.c
 * @brief Moving average and peak detector, see temp_proc.h. Pure C: no ESP-IDF includes, so
 *        tests/firmware/test_temp_proc.c runs it on the PC.
 */
#include "temp_proc.h"
#include "app_config.h"

#include <string.h>

/* ------------------------------ moving average ------------------------------ */

void temp_avg_reset(temp_avg_t *avg)
{
    memset(avg, 0, sizeof *avg);
}

void temp_avg_push(temp_avg_t *avg, uint32_t t_ms, float temp_c)
{
    if (avg->count == 0) {
        avg->first_t_ms = t_ms;
    }
    avg->t_ms[avg->head] = t_ms;
    avg->temp_c[avg->head] = temp_c;
    avg->head = (uint16_t)((avg->head + 1) % TEMP_AVG_CAPACITY);
    if (avg->count < TEMP_AVG_CAPACITY) {
        avg->count++;
    }
}

bool temp_avg_compute(const temp_avg_t *avg, uint32_t now_ms, uint32_t window_ms,
                      temp_avg_result_t *out)
{
    /* The order of the samples does not matter for a sum, so the ring is scanned as is. */
    double sum = 0.0;
    uint16_t n = 0;
    for (uint16_t i = 0; i < avg->count; i++) {
        /* t - W < t_i <= t  is  0 <= t - t_i < W. Unsigned, so it also holds across the uint32
         * wrap, and a sample newer than now_ms gives a huge age and is left out. */
        uint32_t age_ms = now_ms - avg->t_ms[i];
        if (age_ms < window_ms) {
            sum += avg->temp_c[i];
            n++;
        }
    }
    if (n == 0) {
        return false;
    }
    out->mean_c = (float)(sum / n);
    out->n = n;
    out->window_complete = (now_ms - avg->first_t_ms) >= window_ms;
    return true;
}

/* ------------------------------ peak detection ------------------------------ */

void temp_peak_reset(temp_peak_t *pk)
{
    memset(pk, 0, sizeof *pk);
}

bool temp_peak_push(temp_peak_t *pk, uint32_t t_ms, float temp_c, float threshold_c,
                    temp_peak_event_t *ev)
{
    if (!pk->started) {                 /* first reading: the bottom until something rises */
        pk->started = true;
        pk->rising = false;
        pk->min_c = temp_c;
        return false;
    }

    if (pk->rising) {
        if (temp_c > pk->max_c) {                           /* still rising: new candidate */
            pk->max_c = temp_c;
            pk->max_t_ms = t_ms;
        } else if (temp_c <= pk->max_c - PEAK_HYSTERESIS_C) {
            /* Fell h below the candidate: it was a peak. Now look for the bottom. */
            pk->rising = false;
            pk->min_c = temp_c;
            if (pk->max_c >= threshold_c) {
                ev->t_ms = pk->max_t_ms;
                ev->peak_c = pk->max_c;
                ev->threshold_c = threshold_c;
                return true;
            }
        }
    } else {
        if (temp_c < pk->min_c) {                           /* still falling: new bottom */
            pk->min_c = temp_c;
        } else if (temp_c >= pk->min_c + PEAK_HYSTERESIS_C) {
            /* Rose h above the bottom: a new rise begins, with this reading as candidate. */
            pk->rising = true;
            pk->max_c = temp_c;
            pk->max_t_ms = t_ms;
        }
    }
    return false;
}
