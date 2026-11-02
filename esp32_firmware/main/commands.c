/**
 * @file commands.c
 * @brief Parses GUI commands (CFG / INIT / BAUD), applies them and replies ACK / ERR.
 *
 * The dispatcher, send_err(), strict field parsing and BAUD come from Tarea 1 unchanged. T1's
 * send_ack() is gone: every T2 acknowledgement carries data (version, rate, applied config),
 * so each handler builds its own ACK payload.
 * See commands.h for the command set and README.md "Protocolo" for the frame definitions.
 */
#include "commands.h"
#include "app_config.h"
#include "protocol.h"
#include "sampler.h"
#include "uart_link.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_log.h"

/** Log tag of this module. */
static const char *TAG = "commands";

/** Maximum number of comma-separated fields a command may carry (CFG uses 7). */
#define MAX_FIELDS 12

/**
 * @brief Send an error frame: "ERR," followed by @p why.
 * @param[in] why  Short reason code: "BADFRAME", "EMPTY", "UNKNOWN", "BADARG" or "NOTIMPL".
 */
static void send_err(const char *why)
{
    char payload[32];
    snprintf(payload, sizeof payload, "ERR,%s", why);
    uart_link_send_frame(payload);
}

/**
 * @brief Parse one numeric command field strictly.
 *
 * Unlike a bare strtol(), this rejects empty fields, trailing garbage ("10x") and values
 * outside [lo, hi], so a later narrowing cast can never wrap (e.g. 260 -> 4 as uint8_t).
 *
 * @param[in]  s    NUL-terminated field text.
 * @param      lo   Smallest accepted value.
 * @param      hi   Largest accepted value.
 * @param[out] out  Parsed value, only written on success.
 * @return true if @p s is a decimal integer within [lo, hi].
 */
static bool parse_field(const char *s, long lo, long hi, long *out)
{
    char *end = NULL;
    long v = strtol(s, &end, 10);
    if (end == s || *end != '\0' || v < lo || v > hi) {
        return false;
    }
    *out = v;
    return true;
}

/**
 * @brief Handle a CFG command: replace the whole runtime configuration. TODO(FW3).
 *
 *     CFG,sampling_hz=..,variables=..,avg_enabled=..,window_s=..,peak_enabled=..,threshold_c=..
 *
 * To do: require all six keys, each exactly once, in strict formats (an exact table for
 * sampling_hz, letters T/H/P without repeats for variables, parse_field() for the integers,
 * exactly one decimal for threshold_c, converted to tenths without going through float);
 * build a sampler_cfg_t and apply it with sampler_set_config(); reply ACK,CFG followed by
 * the applied configuration in the same key=value form. Any failure replies ERR,BADARG
 * (naming the offending key is a cheap help for the GUI) and changes nothing.
 *
 * @param fields  Payload fields as split by proto_split(); fields[0] is "CFG".
 * @param n       Number of entries in @p fields.
 */
static void handle_cfg(char *fields[], int n)
{
    (void)fields;
    (void)n;
    send_err("NOTIMPL");
}

/**
 * @brief Handle a BAUD command: change the speed of the link itself (from Tarea 1).
 *
 *     BAUD,<115200|230400|460800|921600>
 *
 * Acquisition is stopped first: a frame still sitting in the TX buffer would otherwise be
 * shifted out half at the old rate and half at the new one. The ACK is sent *before* the
 * switch so the PC receives it at the rate it is still listening at, and doubles as its cue
 * to switch; uart_link_set_baud() then drains the buffer and reprograms the divisor.
 *
 * The new rate is provisional until a frame arrives at it (commands_handle_line() confirms),
 * so a rate the PC cannot drive costs LINK_BAUD_REVERT_MS, not a trip to the reset button.
 * The PC is expected to send INIT once it has switched, which both confirms the rate and
 * restarts the acquisition stopped here.
 *
 * Replies `ACK,BAUD,<baud>` on success, or ERR,BADARG for a bad field count or a rate outside
 * the allowed set.
 *
 * @param[in] fields  Payload fields as split by proto_split(); fields[0] is "BAUD".
 * @param     n       Number of entries in @p fields.
 */
static void handle_baud(char *fields[], int n)
{
    long baud;
    if (n != 2 || !parse_field(fields[1], 0, 1000000, &baud) ||
        !uart_link_valid_baud((unsigned)baud)) {
        send_err("BADARG");
        return;
    }

    sampler_stop();

    char payload[32];
    snprintf(payload, sizeof payload, "ACK,BAUD,%ld", baud);
    uart_link_send_frame(payload);

    if (!uart_link_set_baud((unsigned)baud)) {
        /* Still at the old rate: the PC will switch anyway on the ACK it has just been
         * sent, stop hearing us, and fall back by itself. Nothing better to report. */
        ESP_LOGE(TAG, "could not switch to %ld baud", baud);
    }
}

/**
 * @brief Handle an INIT command: restore the defaults and (re)start acquisition.
 *
 *     INIT
 *
 * Acquisition is stopped and the configuration reset before the ACK, and restarted after it,
 * so the GUI resets its panels on the ACK and every sample that follows already uses the
 * defaults (same ordering rule as Tarea 1). Acquisition starts only here, never at boot.
 *
 * The sensor is deliberately not re-initialised from here: this runs in the RX task, and
 * after boot only the acquisition task may touch the BME688 (bme688.h); retrying a missing
 * sensor is its job (TODO(FW6)).
 *
 * @param fields  Unused.
 * @param n       Unused.
 */
static void handle_init(char *fields[], int n)
{
    (void)fields;
    (void)n;
    sampler_stop();
    sampler_reset_defaults();

    char payload[32];
    snprintf(payload, sizeof payload, "ACK,INIT,%s", FW_VERSION);
    uart_link_send_frame(payload);

    sampler_start();
}

void commands_handle_line(const char *line)
{
    char payload[LINK_MAX_LINE];
    if (!proto_parse(line, payload, sizeof payload)) {
        /* Noise, an echo, or a bad checksum: report it but never crash or reset state. */
        ESP_LOGW(TAG, "rejected line: %s", line);
        send_err("BADFRAME");
        return;
    }

    char *fields[MAX_FIELDS];
    int n = proto_split(payload, fields, MAX_FIELDS);
    if (n == 0) {
        send_err("EMPTY");
        return;
    }

    /* A frame that passed the checksum proves the PC is talking at the current rate, so a
     * link speed set by a recent BAUD command is now confirmed (no-op otherwise). */
    uart_link_confirm_baud();

    if (strcmp(fields[0], "CFG") == 0) {
        handle_cfg(fields, n);
    } else if (strcmp(fields[0], "INIT") == 0) {
        handle_init(fields, n);
    } else if (strcmp(fields[0], "BAUD") == 0) {
        handle_baud(fields, n);
    } else {
        send_err("UNKNOWN");
    }
}
