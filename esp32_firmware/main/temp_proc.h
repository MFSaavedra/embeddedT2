/**
 * @file temp_proc.h
 * @brief On-device temperature processing (spec 3): time-window moving average and
 *        local-maximum peak detection.
 *
 * Pure C with no ESP-IDF, FreeRTOS or logging dependency, on purpose: tests/ compiles this
 * file with the host compiler (tests/test_firmware_host.py), which is how spec tests 6.4 and
 * 6.5 get reproducible evidence ("comparar con un cálculo de referencia", "la prueba unitaria
 * puede usar una serie conocida"). Keep it that way: all state lives in structs the caller
 * owns, time is passed in, nothing reads a clock.
 *
 * Both algorithms are fed every real temperature reading, whether or not T is selected for
 * transmission (spec 2.2: hiding T must not stop the processing).
 *
 * Scaffold status: API and required semantics are fixed here; the bodies are TODO(FW4) and
 * TODO(FW5).
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/**
 * Samples retained for the average: the longest window (60 s) at the fastest rate (5 Hz) is
 * 300 samples, plus margin for timing jitter. Retention does not depend on the current W, so
 * a longer W immediately uses the samples already held (spec 3.1).
 */
#define TEMP_AVG_CAPACITY 320

/** Retained (time, temperature) samples of the moving average. Treat as opaque. */
typedef struct {
    uint32_t t_ms[TEMP_AVG_CAPACITY];    /**< Sample times, ms on the ESP32 clock. */
    float    temp_c[TEMP_AVG_CAPACITY];  /**< Sample temperatures, degrees C. */
    uint16_t head;                       /**< Next write index. */
    uint16_t count;                      /**< Valid entries, saturating at TEMP_AVG_CAPACITY. */
    uint32_t first_t_ms;                 /**< Time of the first sample since the last reset. */
} temp_avg_t;

/** Result of temp_avg_compute(). */
typedef struct {
    float    mean_c;           /**< Mean of the samples inside the window, C (`temp_avg_c` on the wire). */
    uint16_t n;                /**< N_W(t): number of samples in the mean, >= 1 for a valid result. */
    bool     window_complete;  /**< False while the data does not span a whole window yet (start-up,
                                    or right after W grew); spec 3.1 asks to report it. */
} temp_avg_result_t;

/**
 * @brief Forget every retained sample (INIT, or a restart of the acquisition).
 * @param[out] avg  State to clear.
 */
void temp_avg_reset(temp_avg_t *avg);

/**
 * @brief Retain one reading, overwriting the oldest once the buffer is full.
 *
 * @param[in,out] avg     State.
 * @param         t_ms    Reading time; non-decreasing between resets.
 * @param         temp_c  Measured temperature (never a substitute value).
 */
void temp_avg_push(temp_avg_t *avg, uint32_t t_ms, float temp_c);

/**
 * @brief Mean of the retained samples inside the window ending at @p now_ms.
 *
 * Required semantics (spec 3.1): T_W(t) = (1/N_W(t)) * sum of T_i over t - W < t_i <= t,
 * defined when N_W(t) >= 1. Changing W only changes this query, never the retained data.
 * Suggested completeness rule: window_complete = (now_ms - first_t_ms) >= window_ms.
 *
 * @param[in]  avg        State.
 * @param      now_ms     End of the window (normally the time of the newest sample).
 * @param      window_ms  W in ms.
 * @param[out] out        Written only when the function returns true.
 * @return true if at least one sample falls in the window.
 */
bool temp_avg_compute(const temp_avg_t *avg, uint32_t now_ms, uint32_t window_ms,
                      temp_avg_result_t *out);

/** Peak-detector state: the last two readings. Treat as opaque. */
typedef struct {
    float    t_km2;     /**< T[k-2], C. */
    float    t_km1;     /**< T[k-1], C. */
    uint32_t t_km1_ms;  /**< Time of T[k-1], ms. */
    uint8_t  seen;      /**< Readings since the last reset, saturating at 2. */
} temp_peak_t;

/** One detected peak: value, threshold applied and timestamp (spec 3.2). */
typedef struct {
    uint32_t t_ms;         /**< Time of the peak sample T[k-1], not of the sample that confirmed it. */
    float    peak_c;       /**< T[k-1], C. */
    float    threshold_c;  /**< Threshold in force when the peak was detected, C. */
} temp_peak_event_t;

/**
 * @brief Forget the history (INIT, or when detection is re-enabled).
 * @param[out] pk  State to clear.
 */
void temp_peak_reset(temp_peak_t *pk);

/**
 * @brief Feed reading T[k] and report whether T[k-1] was a peak.
 *
 * Minimum accepted definition (spec 3.2), checked when T[k] arrives:
 * T[k-1] > T[k-2]  and  T[k-1] >= T[k]  and  T[k-1] >= threshold.
 * The strict rise / non-strict fall reports an exact plateau once, at its first sample.
 * Exceeding the threshold alone is NOT a peak (spec 3.2, "Distinción conceptual").
 * TODO(FW5): the minimum rule fires on every noise wiggle above the threshold; pick a
 * spurious-detection strategy (TODO.md "Design decisions") and document it in README.
 *
 * @param[in,out] pk           State.
 * @param         t_ms         Time of T[k].
 * @param         temp_c       T[k], C.
 * @param         threshold_c  Threshold in force, C (0.1 C resolution).
 * @param[out]    ev           Written only when the function returns true.
 * @return true if T[k-1] is a new peak.
 */
bool temp_peak_push(temp_peak_t *pk, uint32_t t_ms, float temp_c, float threshold_c,
                    temp_peak_event_t *ev);
