/**
 * @file uart_link.c
 * @brief UART0 driver setup, frame TX and the line-oriented RX task, see uart_link.h.
 */
#include "uart_link.h"
#include "app_config.h"
#include "protocol.h"

#include <string.h>

#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

/** Log tag of this module. */
static const char *TAG = "uart_link";

/** Line callback registered by uart_link_start_rx_task(). */
static uart_line_cb_t s_line_cb;

/** One-shot timer that undoes an unconfirmed uart_link_set_baud(), created on first use. */
static esp_timer_handle_t s_revert_timer;
/** True between uart_link_set_baud() and uart_link_confirm_baud() (or the revert). */
static volatile bool s_revert_armed;

void uart_link_init(void)
{
    const uart_config_t cfg = {
        .baud_rate  = LINK_BAUD,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(LINK_UART_NUM, LINK_RX_BUF_SIZE, LINK_TX_BUF_SIZE, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(LINK_UART_NUM, &cfg));
    /* UART0 pins already go to the USB bridge: no uart_set_pin() needed. */

    /* Route stdout/ESP_LOG through the same driver so a log line can never be spliced
     * byte-by-byte into the middle of a data frame. Log lines still show up on the PC,
     * but as separate lines that do not start with '$', which the GUI parser ignores. */
    uart_vfs_dev_use_driver(LINK_UART_NUM);

    ESP_LOGI(TAG, "UART%d ready at %d baud", (int)LINK_UART_NUM, LINK_BAUD);
}

bool uart_link_valid_baud(unsigned baud)
{
    return baud == 115200 || baud == 230400 || baud == 460800 || baud == 921600;
}

/**
 * @brief Revert timer callback: nobody talked to us at the new rate, so go back.
 *
 * Runs in the esp_timer task. The warning goes out at LINK_BAUD, i.e. at the rate a GUI
 * that also gave up and reverted is listening at, so it is readable when it matters.
 *
 * @param arg  Unused (esp_timer callback argument).
 */
static void on_revert(void *arg)
{
    (void)arg;
    s_revert_armed = false;
    /* No ESP_ERROR_CHECK here: this is the recovery path. A timeout draining a TX buffer
     * nobody is reading must not turn a bad baud rate into a panic. */
    uart_wait_tx_done(LINK_UART_NUM, pdMS_TO_TICKS(200));
    uart_set_baudrate(LINK_UART_NUM, LINK_BAUD);
    uart_flush_input(LINK_UART_NUM);
    ESP_LOGW(TAG, "no frame received at the new rate, reverted to %d baud", LINK_BAUD);
}

bool uart_link_set_baud(unsigned baud)
{
    if (!uart_link_valid_baud(baud)) {
        return false;
    }
    if (s_revert_timer == NULL) {
        const esp_timer_create_args_t args = {
            .callback        = on_revert,
            .arg             = NULL,
            .dispatch_method = ESP_TIMER_TASK,
            .name            = "baud_revert",
        };
        ESP_ERROR_CHECK(esp_timer_create(&args, &s_revert_timer));
    }
    if (s_revert_armed) {                  /* a second switch before the first was confirmed */
        esp_timer_stop(s_revert_timer);
        s_revert_armed = false;
    }

    /* Everything already queued - the ACK that tells the PC to switch, and any log line
     * ahead of it - must reach the wire at the OLD rate before the divisor changes. */
    ESP_LOGI(TAG, "switching link to %u baud (provisional)", baud);
    if (uart_wait_tx_done(LINK_UART_NUM, pdMS_TO_TICKS(200)) != ESP_OK ||
        uart_set_baudrate(LINK_UART_NUM, baud) != ESP_OK) {
        return false;
    }
    uart_flush_input(LINK_UART_NUM);       /* bytes clocked in mid-switch are garbage */

    s_revert_armed = true;
    ESP_ERROR_CHECK(esp_timer_start_once(s_revert_timer, (uint64_t)LINK_BAUD_REVERT_MS * 1000ULL));
    return true;
}

void uart_link_confirm_baud(void)
{
    if (!s_revert_armed) {
        return;
    }
    s_revert_armed = false;
    /* Unchecked on purpose: the revert timer may have fired between the test above and
     * here (RX task vs. esp_timer task), and stopping an expired timer is not an error
     * worth panicking over - the rate is back to LINK_BAUD either way. */
    esp_timer_stop(s_revert_timer);
    ESP_LOGI(TAG, "link speed confirmed by the PC");
}

void uart_link_send_raw(const char *data, size_t len)
{
    /* uart_write_bytes() serialises concurrent callers with the driver's own mutex, so a
     * frame written in one call is never interleaved with another task's frame. */
    uart_write_bytes(LINK_UART_NUM, data, len);
}

void uart_link_send_frame(const char *payload)
{
    char frame[LINK_MAX_FRAME];
    int n = proto_build(frame, sizeof frame, payload);
    if (n < 0) {
        ESP_LOGW(TAG, "frame too long, dropped (%u payload bytes)", (unsigned)strlen(payload));
        return;
    }
    uart_link_send_raw(frame, (size_t)n);
}

/**
 * @brief RX task body: read bytes from the PC, split on CR/LF and deliver complete lines.
 *
 * Empty lines (e.g. the LF of a CR+LF pair) are skipped. A line that does not fit in
 * LINK_MAX_LINE is dropped; any bytes that follow are collected as the start of a new line.
 * Never returns.
 *
 * @param arg  Unused (FreeRTOS task parameter).
 */
static void rx_task(void *arg)
{
    (void)arg;
    static char line[LINK_MAX_LINE];
    size_t pos = 0;
    uint8_t buf[64];

    for (;;) {
        int n = uart_read_bytes(LINK_UART_NUM, buf, sizeof buf, pdMS_TO_TICKS(20));
        for (int i = 0; i < n; i++) {
            char c = (char)buf[i];
            if (c == '\n' || c == '\r') {
                if (pos > 0) {
                    line[pos] = '\0';
                    s_line_cb(line);
                    pos = 0;
                }
            } else if (pos < sizeof line - 1) {
                line[pos++] = c;
            } else {
                pos = 0;                                /* overlong garbage: discard the line */
            }
        }
    }
}

void uart_link_start_rx_task(uart_line_cb_t cb)
{
    s_line_cb = cb;
    xTaskCreate(rx_task, "uart_rx", 4096, NULL, 10, NULL);
}
