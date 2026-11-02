/**
 * @file sampler.c
 * @brief The acquisition task and the live configuration it runs with. Public API: sampler.h.
 *
 * One cycle per sampling period:
 *
 *     read the BME688 ─▶ error?  ─▶ SMP,seq,t_ms,error=..   (never a value: spec 2.1.2)
 *                    └─▶ T into temp_proc (always) ─▶ SMP with the selected variables
 *                                                     (+ temp_avg_c if the average is on)
 *                                                  └▶ PEAK if a peak was confirmed and
 *                                                     peak detection is on
 */
#include "sampler.h"
#include "app_config.h"
#include "bme688.h"
#include "temp_proc.h"
#include "uart_link.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

/** Log tag of this module. */
static const char *TAG = "sampler";

/* Everything below is guarded by s_lock. The acquisition task holds it for a whole cycle. */
static SemaphoreHandle_t s_lock;    /**< Mutex for the configuration and the acquisition state. */
static sampler_cfg_t     s_cfg;     /**< Configuration in force. */
static bool              s_running; /**< True between sampler_start() and sampler_stop(). */
static uint32_t          s_seq;     /**< Sequence number of the next SMP frame. */
static temp_avg_t        s_avg;     /**< Retained temperatures for the moving average (~2.5 KB). */
static temp_peak_t       s_peak;    /**< Peak-detector state. */

/* --------------------------------- one cycle --------------------------------- */

/**
 * @brief printf-style append to a payload being built.
 * @param buf   Payload so far, NUL-terminated.
 * @param size  Capacity of @p buf. Text that does not fit is cut, and the frame is then too
 *              long for uart_link, which drops it (it never happens with LINK_MAX_FRAME).
 * @param fmt   Format string, then its arguments.
 */
static void append(char *buf, size_t size, const char *fmt, ...)
{
    const size_t len = strlen(buf);
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf + len, size - len, fmt, ap);
    va_end(ap);
}

/**
 * @brief Take one reading, re-initialising the sensor first if needed.
 *
 * The sensor is not ready after a failed bme688_init() at boot or after a failed read; it is
 * re-initialised here, from the only task allowed to use it, so the acquisition recovers on
 * its own once the sensor answers again.
 *
 * @param[out] r  The reading, valid only on success.
 * @return NULL on success, otherwise the error code for the SMP frame.
 */
static const char *read_sensor(bme688_reading_t *r)
{
    if (!bme688_is_ready() && bme688_init() != ESP_OK) {
        return "no_sensor";
    }
    if (bme688_read(r) != ESP_OK) {
        return "read_failed";
    }
    return NULL;
}

/**
 * @brief One acquisition cycle: read, process, send. Called with s_lock held.
 * @param cfg  Configuration in force.
 */
static void run_cycle(const sampler_cfg_t *cfg)
{
    char payload[LINK_MAX_FRAME];
    const uint32_t t_ms = (uint32_t)(esp_timer_get_time() / 1000);   /* start of the measurement */
    snprintf(payload, sizeof payload, "SMP,seq=%lu,t_ms=%lu",
             (unsigned long)s_seq++, (unsigned long)t_ms);

    bme688_reading_t r;
    const char *error = read_sensor(&r);
    if (error != NULL) {
        append(payload, sizeof payload, ",error=%s", error);        /* no values, ever */
        uart_link_send_frame(payload);
        return;
    }

    /* Temperature always feeds the processing, whatever is selected for transmission (spec 2.2). */
    temp_avg_push(&s_avg, t_ms, r.temperature_c);
    temp_peak_event_t peak;
    const bool new_peak = temp_peak_push(&s_peak, t_ms, r.temperature_c,
                                         cfg->threshold_dc / 10.0f, &peak);

    if (cfg->vars & SAMPLER_VAR_T) {
        append(payload, sizeof payload, ",temperature_c=%.2f", r.temperature_c);
    }
    if (cfg->vars & SAMPLER_VAR_H) {
        append(payload, sizeof payload, ",humidity_pct=%.2f", r.humidity_pct);
    }
    if (cfg->vars & SAMPLER_VAR_P) {
        append(payload, sizeof payload, ",pressure_hpa=%.2f", r.pressure_hpa);
    }
    temp_avg_result_t avg;
    if (cfg->avg_enabled &&
        temp_avg_compute(&s_avg, t_ms, cfg->avg_window_s * 1000u, &avg)) {
        append(payload, sizeof payload, ",temp_avg_c=%.2f,avg_n=%u,avg_window_complete=%d",
               avg.mean_c, (unsigned)avg.n, (int)avg.window_complete);
    }
    uart_link_send_frame(payload);

    if (new_peak && cfg->peak_enabled) {
        snprintf(payload, sizeof payload, "PEAK,t_ms=%lu,peak_c=%.2f,threshold_c=%.1f",
                 (unsigned long)peak.t_ms, peak.peak_c, peak.threshold_c);
        uart_link_send_frame(payload);
    }
}

/**
 * @brief Acquisition task: one cycle per sampling period while running.
 *
 * Paced by xTaskDelayUntil() with the period read from the configuration on every cycle, so
 * a rate change applies from the next reading on, without a restart (spec 2.1.4). The
 * shortest period (200 ms) leaves ample room for the ~50 ms the reading takes.
 *
 * @param arg  Unused (FreeRTOS task parameter).
 */
static void acquisition_task(void *arg)
{
    (void)arg;
    TickType_t last_wake = xTaskGetTickCount();
    for (;;) {
        xSemaphoreTake(s_lock, portMAX_DELAY);
        const sampler_cfg_t cfg = s_cfg;
        if (s_running) {
            run_cycle(&cfg);
        }
        xSemaphoreGive(s_lock);
        xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(cfg.period_ms));
    }
}

/* ------------------------------- configuration -------------------------------- */

bool sampler_set_config(const sampler_cfg_t *cfg)
{
    if (!sampler_cfg_valid(cfg)) {
        return false;
    }
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_cfg = *cfg;
    xSemaphoreGive(s_lock);

    char text[160];
    sampler_cfg_format(cfg, text, sizeof text);
    ESP_LOGI(TAG, "config: %s", text);
    return true;
}

sampler_cfg_t sampler_get_config(void)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    const sampler_cfg_t cfg = s_cfg;
    xSemaphoreGive(s_lock);
    return cfg;
}

void sampler_reset_defaults(void)
{
    const sampler_cfg_t defaults = sampler_cfg_default();
    sampler_set_config(&defaults);
}

/* ---------------------------------- lifecycle --------------------------------- */

void sampler_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    sampler_reset_defaults();
    xTaskCreate(acquisition_task, "acquisition", SAMPLER_TASK_STACK, NULL,
                SAMPLER_TASK_PRIORITY, NULL);
}

void sampler_start(void)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_seq = 0;
    temp_avg_reset(&s_avg);
    temp_peak_reset(&s_peak);
    s_running = true;
    xSemaphoreGive(s_lock);
    ESP_LOGI(TAG, "acquisition started");
}

void sampler_stop(void)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);  /* waits for a cycle in progress to finish */
    s_running = false;
    xSemaphoreGive(s_lock);
    ESP_LOGI(TAG, "acquisition stopped");
}
