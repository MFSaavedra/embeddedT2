/**
 * @file protocol.h
 * @brief Frame layer shared by both directions of the serial link.
 *
 * Frame format (ASCII, one frame per line):
 *
 *     $<payload>*<XX>\n
 *
 * - `payload`: comma-separated fields, the first one is the message type (e.g. "BAUD,115200")
 * - `XX`: two upper-case hex digits = XOR of every payload byte (between '$' and '*')
 *
 * This file only knows about framing and checksums. Message types and their fields are
 * defined in README.md ("Protocolo") and handled in commands.c (PC -> ESP32) and sampler.c (ESP32 -> PC).
 * gui_python/protocol.py mirrors this exactly - keep both in sync.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/**
 * @brief XOR checksum of a payload.
 *
 * @param[in] payload  Bytes to checksum (need not be NUL-terminated).
 * @param     len      Number of bytes of @p payload to include.
 *
 * @return XOR of the first @p len bytes of @p payload; 0 for an empty payload.
 */
uint8_t proto_checksum(const char *payload, size_t len);

/**
 * @brief Build a complete frame ('$' + payload + '*' + checksum + newline) into a caller buffer.
 *
 * @param[out] out       Destination buffer; NUL-terminated on success.
 * @param      out_size  Capacity of @p out in bytes, including the NUL.
 * @param[in]  payload   NUL-terminated payload without '$', '*' or checksum.
 *
 * @return Number of bytes written (excluding the NUL), or -1 if @p out_size is too small
 *         (@p out then holds a truncated, unusable frame).
 */
int proto_build(char *out, size_t out_size, const char *payload);

/**
 * @brief Validate a received line and extract its payload.
 *
 * Accepts exactly one frame as described in the file header: a leading '$', a non-empty
 * payload, '*', two hex digits (either case) and nothing else. CR/LF must already have been
 * stripped by the caller.
 *
 * @param[in]  line         NUL-terminated line, without CR/LF.
 * @param[out] payload_out  Receives the payload as a NUL-terminated string on success.
 * @param      out_size     Capacity of @p payload_out in bytes, including the NUL.
 *
 * @return true if @p line is a well-formed frame whose checksum matches; false otherwise
 *         (@p payload_out is left untouched).
 */
bool proto_parse(const char *line, char *payload_out, size_t out_size);

/**
 * @brief Split a payload in place on ',' and collect pointers to each field.
 *
 * Each separating ',' is overwritten with a NUL, so the pointers in @p fields refer to
 * substrings of @p payload. Fields beyond @p max_fields are silently dropped.
 *
 * @param[in,out] payload     NUL-terminated payload; modified in place.
 * @param[out]    fields      Array receiving one pointer per field.
 * @param         max_fields  Capacity of @p fields.
 *
 * @return Number of pointers stored in @p fields (at most @p max_fields).
 */
int proto_split(char *payload, char *fields[], int max_fields);
