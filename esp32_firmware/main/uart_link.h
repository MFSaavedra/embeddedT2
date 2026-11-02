/**
 * @file uart_link.h
 * @brief UART0 setup, frame transmission and line-oriented reception.
 *
 * Thin wrapper around the ESP-IDF UART driver: uart_link_init() configures LINK_UART_NUM,
 * uart_link_send_frame() wraps a payload with the protocol.h framing and writes it, and a
 * background task (uart_link_start_rx_task()) splits incoming bytes into lines for the
 * command layer.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>

/**
 * @brief Callback invoked by the RX task for each complete line received from the PC.
 *
 * @param line  NUL-terminated line with CR/LF stripped. Only valid for the duration of the
 *              call; copy it if it must outlive the callback.
 */
typedef void (*uart_line_cb_t)(const char *line);

/**
 * @brief Install the UART driver on LINK_UART_NUM at LINK_BAUD and route stdout through it.
 *
 * Routing stdout / ESP_LOG through the same driver guarantees that a log line is never
 * spliced byte-by-byte into the middle of a data frame. Must be called once, before any
 * other function of this module.
 */
void uart_link_init(void);

/**
 * @brief Frame @p payload with proto_build() and transmit it.
 *
 * Thread-safe: the whole frame is handed to the driver in a single write, so frames from
 * different tasks are never interleaved. A frame that does not fit in LINK_MAX_FRAME is
 * logged and dropped.
 *
 * @param[in] payload  NUL-terminated payload without '$', '*' or checksum.
 */
void uart_link_send_frame(const char *payload);

/**
 * @brief Transmit raw bytes without framing.
 *
 * Used internally by uart_link_send_frame(); exposed for debugging only. Blocks until the
 * bytes have been copied into the driver's TX ring buffer.
 *
 * @param[in] data  Bytes to send.
 * @param     len   Number of bytes.
 */
void uart_link_send_raw(const char *data, size_t len);

/**
 * @brief Start the background task that reads lines from the PC and hands them to @p cb.
 *
 * @param cb  Called from the RX task context for every non-empty line. Lines that do not
 *            fit in LINK_MAX_LINE are discarded.
 */
void uart_link_start_rx_task(uart_line_cb_t cb);

/**
 * @brief Check that @p baud is one of the rates the GUI offers.
 * @param baud  Raw value from a BAUD command.
 * @return true if @p baud is 115200, 230400, 460800 or 921600.
 */
bool uart_link_valid_baud(unsigned baud);

/**
 * @brief Change the link speed, after everything already queued has left the wire.
 *
 * Call this *after* sending the frame that tells the PC to switch: the pending TX buffer
 * is drained first (uart_wait_tx_done()), so that frame still goes out at the old rate and
 * the PC has something to synchronise on. Bytes clocked in during the changeover are
 * garbage and are discarded.
 *
 * The new rate is provisional: a timer is armed for LINK_BAUD_REVERT_MS and the rate falls
 * back to LINK_BAUD unless uart_link_confirm_baud() is called before it expires. Without
 * that, selecting a rate the PC cannot drive would leave the board mute until it is reset
 * by hand.
 *
 * @param baud  New rate; must satisfy uart_link_valid_baud().
 * @return true if the driver accepted the new rate (the revert timer is then armed).
 *
 * @note Call from a task, never from a timer or ISR: it blocks while the TX buffer drains.
 */
bool uart_link_set_baud(unsigned baud);

/**
 * @brief Confirm the current link speed and cancel the pending revert.
 *
 * Called by the command layer for every frame that passes the checksum: a readable frame at
 * the new rate proves both ends agree. A no-op when no switch is pending.
 */
void uart_link_confirm_baud(void);
