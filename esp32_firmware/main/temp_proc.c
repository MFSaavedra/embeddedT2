/**
 * @file temp_proc.c
 * @brief Moving average and peak detector, see temp_proc.h. Pure C: no ESP-IDF includes.
 *
 * Scaffold: the reset functions work, the rest is TODO(FW4) / TODO(FW5).
 * tests/test_firmware_host.py compiles this file on the host to keep it dependency-free.
 */
#include "temp_proc.h"

#include <string.h>

void temp_avg_reset(temp_avg_t *avg)
{
    memset(avg, 0, sizeof *avg);
}

void temp_avg_push(temp_avg_t *avg, uint32_t t_ms, float temp_c)
{
    /* TODO(FW4): append (t_ms, temp_c) at head, wrap at TEMP_AVG_CAPACITY, saturate count,
     * remember first_t_ms on the first sample after a reset. */
    (void)avg;
    (void)t_ms;
    (void)temp_c;
}

bool temp_avg_compute(const temp_avg_t *avg, uint32_t now_ms, uint32_t window_ms,
                      temp_avg_result_t *out)
{
    /* TODO(FW4): mean over now_ms - window_ms < t_i <= now_ms (unsigned differences, so the
     * comparison stays right across the uint32 wrap), plus n and window_complete. */
    (void)avg;
    (void)now_ms;
    (void)window_ms;
    (void)out;
    return false;
}

void temp_peak_reset(temp_peak_t *pk)
{
    memset(pk, 0, sizeof *pk);
}

bool temp_peak_push(temp_peak_t *pk, uint32_t t_ms, float temp_c, float threshold_c,
                    temp_peak_event_t *ev)
{
    /* TODO(FW5): once two readings are held, test T[k-1] against T[k-2], T[k] and the
     * threshold; then shift: T[k-2] <- T[k-1], T[k-1] <- T[k]. */
    (void)pk;
    (void)t_ms;
    (void)temp_c;
    (void)threshold_c;
    (void)ev;
    return false;
}
