/**
 * @file temp_proc.h
 * @brief On-device temperature processing (spec 3): time-window moving average and peak
 *        detection.
 *
 * Pure C with no ESP-IDF, FreeRTOS or logging dependency, on purpose: tests/ compiles this
 * file with the host compiler (tests/test_firmware_host.py) and feeds it known series, which
 * is the evidence spec tests 6.4 and 6.5 ask for ("comparar con un cálculo de referencia",
 * "la prueba unitaria puede usar una serie conocida"). All state lives in structs the caller
 * owns, and time is passed in: nothing reads a clock.
 *
 * The acquisition task (sampler.c) feeds every real temperature reading to both algorithms,
 * whether or not T is selected for transmission and whether or not the average or the peak
 * detection is enabled (spec 2.2: hiding T must not stop the processing). Enabling only
 * decides what is *sent*.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/* ------------------------------ moving average ------------------------------ */

/**
 * Samples retained for the average: the longest window (60 s) at the fastest rate (5 Hz) is
 * 300 samples, plus margin for timing jitter. Retention does not depend on the current W, so
 * a longer W immediately uses the samples already held (spec 3.1).
 */
#define TEMP_AVG_CAPACITY 320

/** Retained (time, temperature) samples of the moving average, as a ring buffer. */
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
    uint16_t n;                /**< N_W(t): number of samples in the mean, always >= 1. */
    bool     window_complete;  /**< False while the acquisition has not yet covered a whole window
                                    (start-up, or right after W grew); spec 3.1 asks to report it. */
} temp_avg_result_t;

/**
 * @brief Forget every retained sample (INIT).
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
 * @brief Mean of the retained samples inside the window that ends at @p now_ms (spec 3.1):
 *
 *     T_W(t) = (1 / N_W(t)) * sum of T_i  over  t - W < t_i <= t
 *
 * Changing W only changes this query, never the retained data, so a new W takes effect at
 * once with the samples already held. The window counts as complete once the acquisition has
 * been running for at least W: now_ms - (first sample time) >= W.
 *
 * @param[in]  avg        State.
 * @param      now_ms     End of the window t (the time of the newest sample).
 * @param      window_ms  W in ms.
 * @param[out] out        Written only when the function returns true.
 * @return true if at least one sample falls in the window (N_W(t) >= 1).
 */
bool temp_avg_compute(const temp_avg_t *avg, uint32_t now_ms, uint32_t window_ms,
                      temp_avg_result_t *out);

/* ------------------------------ peak detection ------------------------------ */

/**
 * Peak-detector state. The detector alternates between two phases: looking for the top of a
 * rise, and looking for the bottom of the fall that follows it.
 */
typedef struct {
    bool     started;   /**< At least one reading since the last reset. */
    bool     rising;    /**< True while looking for the top of a rise, false while looking for the bottom. */
    float    max_c;     /**< Highest reading of the current rise, C. */
    uint32_t max_t_ms;  /**< Time of that reading, ms. */
    float    min_c;     /**< Lowest reading of the current fall, C. */
} temp_peak_t;

/** One detected peak: value, threshold applied and timestamp (spec 3.2). */
typedef struct {
    uint32_t t_ms;         /**< Time of the peak sample itself, not of the sample that confirmed it. */
    float    peak_c;       /**< The peak temperature, C. */
    float    threshold_c;  /**< Threshold in force when the peak was confirmed, C. */
} temp_peak_event_t;

/**
 * @brief Forget the history (INIT).
 * @param[out] pk  State to clear.
 */
void temp_peak_reset(temp_peak_t *pk);

/**
 * @brief Feed one reading; report a peak when one is confirmed.
 *
 * Criterion (README "Detección de picos"): a peak is a local maximum that stands out from its
 * surroundings by at least the hysteresis h = PEAK_HYSTERESIS_C (app_config.h) and reaches
 * the threshold:
 *  - while rising, every new maximum becomes the candidate; once a reading falls h below the
 *    candidate, the candidate was a peak, and it is reported if it is >= threshold;
 *  - then, while falling, the minimum is tracked; once a reading rises h above it, a new rise
 *    begins. Only then can the next peak be found.
 *
 * Consequences: a ramp, however far above the threshold, is never a peak (spec 3.2,
 * "Distinción conceptual"); wiggles smaller than h (sensor noise) are never peaks; each peak
 * is reported exactly once; a plateau is reported at its first sample. A reported peak always
 * satisfies the spec's minimum rule: it is above the sample before it, at least the sample
 * after it, and >= threshold. The detector starts in the falling phase, so the first peak
 * needs a rise of h first.
 *
 * @param[in,out] pk           State.
 * @param         t_ms         Time of this reading.
 * @param         temp_c       This reading, C.
 * @param         threshold_c  Threshold in force, C (0.1 C resolution).
 * @param[out]    ev           Written only when the function returns true.
 * @return true if this reading confirmed a peak (reported in @p ev with its own time).
 */
bool temp_peak_push(temp_peak_t *pk, uint32_t t_ms, float temp_c, float threshold_c,
                    temp_peak_event_t *ev);
