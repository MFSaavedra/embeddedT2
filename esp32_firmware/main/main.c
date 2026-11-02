/**
 * @file main.c
 * @brief Tarea 2 - CC5328 (Sistemas Embebidos y Sensores): BME688 acquisition firmware.
 *
 * Reads temperature, relative humidity and pressure from a BME688 over I2C, computes a moving
 * average and detects peaks of the temperature on the ESP32, and streams only the selected
 * variables to a PyQt GUI over UART0 (USB-serial), accepting configuration commands at run time.
 *
 * Module map (one responsibility per file):
 * - uart_link.c  - UART0 driver, frame TX, line-oriented RX task, runtime baud change (from T1)
 * - protocol.c   - "$payload*XX" framing + XOR checksum, mirrored by gui_python/protocol.py (from T1)
 * - commands.c   - parses GUI commands (CFG / INIT / BAUD) and applies them
 * - bme688.c     - I2C bus and BME688 driver (T/H/P, gas heater off)
 * - sampler.c    - atomic runtime configuration and the acquisition task (SMP / PEAK frames)
 * - temp_proc.c  - moving average + peak detector, pure C so it is unit-tested on the host
 * - app_config.h - spec defaults, I2C pins and compile-time constants
 */
#include "app_config.h"
#include "bme688.h"
#include "commands.h"
#include "sampler.h"
#include "uart_link.h"

#include "esp_err.h"
#include "esp_log.h"

/** Log tag of this module. */
static const char *TAG = "main";

/**
 * @brief Application entry point: bring up every module and start listening for commands.
 *
 * A missing sensor is not fatal: commands are still answered, and the acquisition reports the
 * fault instead of sending values (TODO(FW6)). Acquisition does NOT start here: it starts when
 * the GUI sends INIT (commands_handle_line() -> handle_init()). Returns after setup; the
 * FreeRTOS tasks created by the modules keep running.
 */
void app_main(void)
{
    uart_link_init();

    esp_err_t err = bme688_init();
    if (err != ESP_OK) {
        /* Only idf.py monitor sees this: the GUI resets the board on connect and discards the
         * boot output, so it must learn about the fault from the acquisition (TODO(FW6)). */
        ESP_LOGE(TAG, "BME688 not available: %s", esp_err_to_name(err));
    }

    sampler_init();
    uart_link_start_rx_task(commands_handle_line);

    ESP_LOGI(TAG, "Tarea2 BME688 firmware ready (link %d baud)", LINK_BAUD);
}
