/**
 * @file protocol.c
 * @brief Framing and XOR checksum, see protocol.h. No dependencies beyond libc.
 */
#include "protocol.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

uint8_t proto_checksum(const char *payload, size_t len)
{
    uint8_t cs = 0;
    for (size_t i = 0; i < len; i++) {
        cs ^= (uint8_t)payload[i];
    }
    return cs;
}

int proto_build(char *out, size_t out_size, const char *payload)
{
    size_t len = strlen(payload);
    uint8_t cs = proto_checksum(payload, len);
    int n = snprintf(out, out_size, "$%s*%02X\n", payload, cs);
    if (n < 0 || (size_t)n >= out_size) {
        return -1;
    }
    return n;
}

bool proto_parse(const char *line, char *payload_out, size_t out_size)
{
    if (line == NULL || line[0] != '$') {
        return false;
    }
    const char *star = strrchr(line, '*');
    if (star == NULL || star == line + 1) {
        return false;                                   /* no '*' or empty payload */
    }
    size_t payload_len = (size_t)(star - (line + 1));
    if (payload_len >= out_size) {
        return false;
    }
    /* exactly two hex digits after '*', then end of line */
    if (!isxdigit((unsigned char)star[1]) || !isxdigit((unsigned char)star[2]) || star[3] != '\0') {
        return false;
    }
    uint8_t expected = (uint8_t)strtoul(star + 1, NULL, 16);
    if (proto_checksum(line + 1, payload_len) != expected) {
        return false;
    }
    memcpy(payload_out, line + 1, payload_len);
    payload_out[payload_len] = '\0';
    return true;
}

int proto_split(char *payload, char *fields[], int max_fields)
{
    int n = 0;
    char *p = payload;
    while (p != NULL && n < max_fields) {
        fields[n++] = p;
        char *comma = strchr(p, ',');
        if (comma == NULL) {
            break;
        }
        *comma = '\0';
        p = comma + 1;
    }
    return n;
}
