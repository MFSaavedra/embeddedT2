/**
 * @file test_temp_proc.c
 * @brief Host-side test of esp32_firmware/main/temp_proc.c with known temperature series
 *        (TODO.md UT1 and UT2; spec tests 6.4 and 6.5).
 *
 * The moving average is compared against a reference computed here, directly from the
 * definition (T_W(t) = mean of the T_i with t - W < t_i <= t). The peak detector is fed
 * series whose peaks are known in advance. Built and run by tests/test_firmware_host.py.
 */
#include "app_config.h"
#include "temp_proc.h"

#include <math.h>
#include <stdio.h>

/** Number of failed CHECK()s. */
static int s_failures;

/** Record a failure with its location instead of aborting, so one run reports every problem. */
#define CHECK(cond)                                                          \
    do {                                                                     \
        if (!(cond)) {                                                       \
            printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);           \
            s_failures++;                                                    \
        }                                                                    \
    } while (0)

/** Two temperatures agree to well below the 0.01 C printed on the wire. */
#define NEAR(a, b) (fabs((double)(a) - (double)(b)) < 1e-4)

/* ------------------------------ moving average ------------------------------ */

/** Big state lives here, not on the stack. */
static temp_avg_t s_avg;

/**
 * @brief Reference mean straight from the spec's definition, over arrays of samples.
 * @param t     Sample times, ms.
 * @param v     Sample temperatures.
 * @param n     Number of samples.
 * @param now   End of the window t.
 * @param w     Window W, ms.
 * @param[out] count  N_W(t).
 * @return The mean (0 if no sample is in the window).
 */
static double reference_mean(const unsigned *t, const float *v, int n, unsigned now, unsigned w,
                             int *count)
{
    double sum = 0.0;
    *count = 0;
    for (int i = 0; i < n; i++) {
        /* t - W < t_i <= t, in signed arithmetic (t - W is negative during start-up) */
        if ((long long)now - (long long)w < (long long)t[i] && t[i] <= now) {
            sum += v[i];
            (*count)++;
        }
    }
    return *count ? sum / *count : 0.0;
}

/** @brief A known 1 Hz series against the reference, for W = 5, 10, 30 s, plus start-up. */
static void test_average_against_reference(void)
{
    enum { N = 40 };
    unsigned t[N];
    float v[N];
    temp_avg_reset(&s_avg);
    temp_avg_result_t r;
    CHECK(!temp_avg_compute(&s_avg, 0, 5000, &r));          /* no sample: no result */

    for (int i = 0; i < N; i++) {
        t[i] = 1000u + 1000u * (unsigned)i;                  /* 1 Hz, starting at t = 1 s */
        v[i] = 24.0f + 0.1f * (float)(i % 7) + (i > 20 ? 1.5f : 0.0f);
        temp_avg_push(&s_avg, t[i], v[i]);

        const unsigned windows_ms[] = { 5000, 10000, 30000 };
        for (int k = 0; k < 3; k++) {
            int n_ref;
            const double mean = reference_mean(t, v, i + 1, t[i], windows_ms[k], &n_ref);
            CHECK(temp_avg_compute(&s_avg, t[i], windows_ms[k], &r));
            CHECK(r.n == n_ref);
            CHECK(NEAR(r.mean_c, mean));
            /* complete once the acquisition has covered a whole window */
            CHECK(r.window_complete == (t[i] - t[0] >= windows_ms[k]));
        }
    }

    /* Spot values: window (35 s, 40 s] holds exactly 5 samples; t - W itself is excluded. */
    CHECK(temp_avg_compute(&s_avg, 40000, 5000, &r) && r.n == 5 && r.window_complete);
    /* Start-up: two samples in a 10 s window, reported incomplete. */
    temp_avg_reset(&s_avg);
    temp_avg_push(&s_avg, 1000, 20.0f);
    temp_avg_push(&s_avg, 2000, 21.0f);
    CHECK(temp_avg_compute(&s_avg, 2000, 10000, &r) && r.n == 2 && NEAR(r.mean_c, 20.5) &&
          !r.window_complete);
}

/** @brief A longer W uses the samples already retained, and reports itself incomplete. */
static void test_window_change_uses_retained_samples(void)
{
    temp_avg_reset(&s_avg);
    for (unsigned i = 0; i < 20; i++) {                      /* 20 s at 1 Hz */
        temp_avg_push(&s_avg, i * 1000u, (float)i);
    }
    temp_avg_result_t r;
    CHECK(temp_avg_compute(&s_avg, 19000, 5000, &r) && r.n == 5 && NEAR(r.mean_c, 17.0) &&
          r.window_complete);
    /* W 5 s -> 30 s: all 20 retained samples count at once; 19 s < 30 s, so incomplete. */
    CHECK(temp_avg_compute(&s_avg, 19000, 30000, &r) && r.n == 20 && NEAR(r.mean_c, 9.5) &&
          !r.window_complete);
}

/** @brief 5 Hz for 80 s overflows the buffer, yet the 60 s window is still whole. */
static void test_buffer_holds_the_longest_window_at_the_fastest_rate(void)
{
    temp_avg_reset(&s_avg);
    for (unsigned i = 0; i < 400; i++) {
        temp_avg_push(&s_avg, i * 200u, (float)(i % 10));
    }
    temp_avg_result_t r;
    /* (19.8 s, 79.8 s] holds samples 100..399: 300 samples, mean of 30 cycles of 0..9. */
    CHECK(temp_avg_compute(&s_avg, 399 * 200u, 60000, &r) && r.n == 300 &&
          NEAR(r.mean_c, 4.5) && r.window_complete);
}

/** @brief Times are uint32 ms since boot: the window works across their wrap (49.7 days). */
static void test_average_across_the_clock_wrap(void)
{
    temp_avg_reset(&s_avg);
    const uint32_t start = UINT32_MAX - 1500u;
    for (uint32_t k = 0; k < 5; k++) {
        temp_avg_push(&s_avg, start + k * 1000u, 25.0f + (float)k);   /* wraps after k = 1 */
    }
    temp_avg_result_t r;
    const uint32_t now = start + 4000u;                       /* 2499 after the wrap */
    CHECK(temp_avg_compute(&s_avg, now, 5000, &r) && r.n == 5 && NEAR(r.mean_c, 27.0) &&
          !r.window_complete);
    CHECK(temp_avg_compute(&s_avg, now, 2500, &r) && r.n == 3 && NEAR(r.mean_c, 28.0));
}

/* ------------------------------ peak detection ------------------------------ */

/** Result of feeding a series to the detector. */
typedef struct {
    int               events;  /**< Peaks reported. */
    temp_peak_event_t last;    /**< The last one. */
    int               at;      /**< Index of the reading that confirmed it. */
} peaks_t;

/**
 * @brief Feed @p n readings, one per second from t = 0, with a fixed threshold.
 * @param v          The series.
 * @param n          Its length.
 * @param threshold  Threshold, C.
 * @return Number of events and the last one.
 */
static peaks_t feed(const float *v, int n, float threshold)
{
    temp_peak_t pk;
    temp_peak_reset(&pk);
    peaks_t out = { 0 };
    for (int i = 0; i < n; i++) {
        temp_peak_event_t ev;
        if (temp_peak_push(&pk, (uint32_t)i * 1000u, v[i], threshold, &ev)) {
            out.events++;
            out.last = ev;
            out.at = i;
        }
    }
    return out;
}

/**
 * @brief How many times the spec's bare minimum rule fires on a series:
 *        T[k-1] > T[k-2], T[k-1] >= T[k], T[k-1] >= threshold.
 */
static int minimum_rule_count(const float *v, int n, float threshold)
{
    int count = 0;
    for (int k = 2; k < n; k++) {
        if (v[k - 1] > v[k - 2] && v[k - 1] >= v[k] && v[k - 1] >= threshold) {
            count++;
        }
    }
    return count;
}

/** @brief One clean peak: one event, with the peak's own value and time, after a fall of h. */
static void test_single_peak(void)
{
    const float v[] = { 24.0f, 24.5f, 25.0f, 25.5f, 26.0f, 25.6f, 25.2f, 24.8f, 24.4f };
    const peaks_t p = feed(v, 9, 25.0f);
    CHECK(p.events == 1);
    CHECK(p.last.t_ms == 4000);                 /* the 26.0 sample, not the confirming one */
    CHECK(NEAR(p.last.peak_c, 26.0) && NEAR(p.last.threshold_c, 25.0));
    CHECK(p.at == 5);                           /* 25.6 <= 26.0 - 0.2 confirms it */
    /* The reported sample satisfies the spec's minimum rule. */
    CHECK(v[4] > v[3] && v[4] >= v[5] && v[4] >= 25.0f);
}

/** @brief A flat top is reported once, at its first sample. */
static void test_plateau(void)
{
    const float v[] = { 24.0f, 25.0f, 26.0f, 26.0f, 26.0f, 26.0f, 25.5f };
    const peaks_t p = feed(v, 7, 25.0f);
    CHECK(p.events == 1 && p.last.t_ms == 2000);
}

/** @brief Spec 3.2, "Distinción conceptual": a ramp above the threshold has no maximum. */
static void test_ramp_above_threshold_is_not_a_peak(void)
{
    float v[60];
    for (int i = 0; i < 60; i++) {
        v[i] = 25.0f + 0.1f * (float)i;         /* 25.0 -> 30.9, always >= threshold */
    }
    CHECK(feed(v, 60, 25.0f).events == 0);
}

/** @brief A local maximum below the threshold is not reported. */
static void test_maximum_below_threshold(void)
{
    const float v[] = { 24.0f, 24.5f, 24.9f, 24.5f, 24.0f };
    CHECK(feed(v, 5, 25.0f).events == 0);
    CHECK(feed(v, 5, 24.9f).events == 1);       /* T >= threshold: reported */
}

/**
 * @brief Sensor noise on a warm plateau: the minimum rule alone fires on every wiggle, the
 *        hysteresis reports the plateau once (TODO.md trap 2).
 */
static void test_noise_above_threshold_gives_one_event(void)
{
    /* Rise, 40 s of +-0.05 C noise around 26.0 (2.5x the 0.02 C rms measured), then fall. */
    static const float wiggle[] = { 0.00f, 0.04f, -0.03f, 0.05f, -0.01f, 0.02f, -0.05f, 0.03f };
    float v[60];
    int n = 0;
    for (float x = 24.0f; x < 26.0f; x += 0.5f) {
        v[n++] = x;
    }
    for (int i = 0; i < 40; i++) {
        v[n++] = 26.0f + wiggle[i % 8];
    }
    for (float x = 25.5f; x > 24.0f; x -= 0.5f) {
        v[n++] = x;
    }
    CHECK(minimum_rule_count(v, n, 25.0f) > 5);
    const peaks_t p = feed(v, n, 25.0f);
    CHECK(p.events == 1);
    CHECK(NEAR(p.last.peak_c, 26.05));          /* the highest wiggle is the peak */
}

/** @brief Two humps separated by a dip of more than h are two peaks. */
static void test_two_peaks(void)
{
    const float v[] = { 24.0f, 25.0f, 26.0f, 25.0f, 24.5f, 25.5f, 27.0f, 26.0f, 25.0f };
    const peaks_t p = feed(v, 9, 25.0f);
    CHECK(p.events == 2 && NEAR(p.last.peak_c, 27.0) && p.last.t_ms == 6000);
}

/** @brief The first reading has no history: a fall right after it is not a peak. */
static void test_no_peak_without_a_rise(void)
{
    const float v[] = { 28.0f, 27.0f, 26.0f };
    CHECK(feed(v, 3, 25.0f).events == 0);
}

/** @brief The threshold in force when the peak is confirmed is the one applied and reported. */
static void test_threshold_in_force_at_confirmation(void)
{
    temp_peak_t pk;
    temp_peak_reset(&pk);
    temp_peak_event_t ev;
    const float v[] = { 24.0f, 25.0f, 26.0f, 25.5f };
    CHECK(!temp_peak_push(&pk, 0, v[0], 30.0f, &ev));
    CHECK(!temp_peak_push(&pk, 1000, v[1], 30.0f, &ev));
    CHECK(!temp_peak_push(&pk, 2000, v[2], 30.0f, &ev));
    /* θ lowered from 30.0 to 25.5 before the fall confirms the peak: it counts, with 25.5. */
    CHECK(temp_peak_push(&pk, 3000, v[3], 25.5f, &ev) && NEAR(ev.threshold_c, 25.5) &&
          ev.t_ms == 2000);
}

/** @brief Run every check; exit status 0 only if all passed. */
int main(void)
{
    test_average_against_reference();
    test_window_change_uses_retained_samples();
    test_buffer_holds_the_longest_window_at_the_fastest_rate();
    test_average_across_the_clock_wrap();
    test_single_peak();
    test_plateau();
    test_ramp_above_threshold_is_not_a_peak();
    test_maximum_below_threshold();
    test_noise_above_threshold_gives_one_event();
    test_two_peaks();
    test_no_peak_without_a_rise();
    test_threshold_in_force_at_confirmation();

    if (s_failures == 0) {
        printf("test_temp_proc: all checks passed (hysteresis %.2f C)\n", PEAK_HYSTERESIS_C);
    }
    return s_failures == 0 ? 0 : 1;
}
