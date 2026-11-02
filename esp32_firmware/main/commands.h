/**
 * @file commands.h
 * @brief Interpretation of GUI -> ESP32 commands.
 *
 * Command set (README.md "Protocolo"):
 *
 *     $CFG,sampling_hz=<0.5|1|2|5>,variables=<T|H|P|TH|TP|HP|THP>,avg_enabled=<0|1>,
 *          window_s=<5|10|30|60>,peak_enabled=<0|1>,threshold_c=<-40.0..85.0>*XX
 *     $INIT*XX
 *     $BAUD,<115200|230400|460800|921600>*XX
 *
 * - CFG replaces the whole runtime configuration atomically (sampler_set_config()) and is
 *   answered with the configuration actually applied: `ACK,CFG,sampling_hz=..,...`.
 * - INIT restores the defaults, replies with the firmware version and (re)starts acquisition.
 * - BAUD changes the speed of the link itself, stopping the acquisition that INIT restarts
 *   (carried over from Tarea 1).
 *
 * Every command is answered with an ACK frame (`ACK,INIT,2.0`, `ACK,BAUD,230400`, ...) or an
 * ERR frame with a reason code: BADFRAME, EMPTY, UNKNOWN or BADARG (`ERR,BADARG,window_s`
 * for a CFG names the first invalid field).
 */
#pragma once

/**
 * @brief Entry point for the UART RX task: validate one line and dispatch on its type.
 *
 * Rejects anything that is not a valid frame (ERR,BADFRAME), then routes CFG / INIT / BAUD to
 * their handlers; unknown types get ERR,UNKNOWN. Never crashes or changes state on bad input,
 * so noise on the shared console is harmless. A frame that passes the checksum also confirms
 * the current link speed (uart_link_confirm_baud()).
 *
 * @param[in] line  NUL-terminated line without CR/LF, as delivered by uart_link.
 *
 * @note Runs in the UART RX task context (see uart_link_start_rx_task()).
 */
void commands_handle_line(const char *line);
