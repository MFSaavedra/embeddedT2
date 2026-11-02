/**
 * @file sampler.c
 * @brief Runtime configuration (validated, atomic) and, TODO(FW2), the acquisition task.
 *
 * Public API: sampler.h.
 */
#include "sampler.h"
#include "app_config.h"

#include <stddef.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"

/** Log tag of this module. */
static const char *TAG = "sampler";

/** Spec defaults, applied by sampler_reset_defaults(). */
static const sampler_cfg_t DEFAULT_CFG = {
    .period_ms    = SAMPLER_DEFAULT_PERIOD_MS,
    .vars         = SAMPLER_VAR_ALL,
    .avg_enabled  = AVG_DEFAULT_ENABLED,
    .avg_window_s = AVG_DEFAULT_WINDOW_S,
    .peak_enabled = PEAK_DEFAULT_ENABLED,
    .threshold_dc = PEAK_DEFAULT_THRESHOLD_DC,
};

static sampler_cfg_t s_cfg;                                       /**< Live configuration, guarded by s_cfg_lock */
static portMUX_TYPE  s_cfg_lock = portMUX_INITIALIZER_UNLOCKED;   /**< Protects s_cfg across tasks */
static volatile bool s_running;                                   /**< True between sampler_start() and sampler_stop() */

/* --------------------------------- validation --------------------------------- */

bool sampler_valid_period(unsigned ms)
{
    return ms == 2000 || ms == 1000 || ms == 500 || ms == 200;
}

bool sampler_valid_vars(unsigned vars)
{
    return vars != 0 && (vars & ~SAMPLER_VAR_ALL) == 0;
}

bool sampler_valid_window(unsigned seconds)
{
    return seconds == 5 || seconds == 10 || seconds == 30 || seconds == 60;
}

bool sampler_valid_threshold(int threshold_dc)
{
    return threshold_dc >= PEAK_MIN_THRESHOLD_DC && threshold_dc <= PEAK_MAX_THRESHOLD_DC;
}

bool sampler_valid_config(const sampler_cfg_t *cfg)
{
    return cfg != NULL && sampler_valid_period(cfg->period_ms) && sampler_valid_vars(cfg->vars) &&
           sampler_valid_window(cfg->avg_window_s) && sampler_valid_threshold(cfg->threshold_dc);
}

/* ------------------------------- configuration -------------------------------- */

bool sampler_set_config(const sampler_cfg_t *cfg)
{
    if (!sampler_valid_config(cfg)) {
        return false;
    }
    portENTER_CRITICAL(&s_cfg_lock);
    s_cfg = *cfg;
    portEXIT_CRITICAL(&s_cfg_lock);
    ESP_LOGI(TAG, "config: period=%u ms vars=%s%s%s avg=%d (W=%u s) peak=%d (theta=%.1f C)",
             (unsigned)cfg->period_ms,
             (cfg->vars & SAMPLER_VAR_T) ? "T" : "", (cfg->vars & SAMPLER_VAR_H) ? "H" : "",
             (cfg->vars & SAMPLER_VAR_P) ? "P" : "", (int)cfg->avg_enabled,
             (unsigned)cfg->avg_window_s, (int)cfg->peak_enabled, cfg->threshold_dc / 10.0);
    return true;
}

sampler_cfg_t sampler_get_config(void)
{
    sampler_cfg_t c;
    portENTER_CRITICAL(&s_cfg_lock);
    c = s_cfg;
    portEXIT_CRITICAL(&s_cfg_lock);
    return c;
}

void sampler_reset_defaults(void)
{
    sampler_set_config(&DEFAULT_CFG);
}

/* ---------------------------------- lifecycle --------------------------------- */

void sampler_init(void)
{
    sampler_reset_defaults();
    /* TODO(FW2): create the acquisition task here (priority below uart_rx's 10, >= 4 KB stack).
     * One cycle, paced by vTaskDelayUntil() with the period re-read from the snapshot every
     * cycle so a rate change applies without a restart (spec 2.1.4):
     *   - skip while !s_running;
     *   - bme688_read(); on failure send the error form of SMP (no values, ever) - FW6;
     *   - push T into temp_proc ALWAYS, whatever cfg.vars says (spec 2.2);
     *   - send SMP with seq + t_ms + only the selected variables, plus temp_avg_c and the
     *     window-complete flag when the average is enabled;
     *   - a peak from temp_peak_push() becomes its own PEAK frame.
     * This task is the sensor's only user after boot (bme688.h), retries included. */
    ESP_LOGI(TAG, "init done; acquisition task is TODO(FW2)");
}

void sampler_start(void)
{
    if (s_running) {
        return;
    }
    s_running = true;
    ESP_LOGI(TAG, "acquisition started");
}

void sampler_stop(void)
{
    if (!s_running) {
        return;
    }
    s_running = false;
    ESP_LOGI(TAG, "acquisition stopped");
}
