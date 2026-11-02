/**
 * @file test_protocol_c.c
 * @brief Host-side test of esp32_firmware/main/protocol.c, mirroring tests/test_protocol.py.
 *
 * Built and run by tests/test_firmware_host.py with the host C compiler. The expected bytes are
 * the Python tests' bytes: that is what keeps protocol.c and protocol.py identical.
 */
#include "protocol.h"

#include <stdio.h>
#include <string.h>

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

/**
 * @brief proto_parse() into a scratch buffer, for the must-reject cases.
 * @param line  Line to validate.
 * @return true if proto_parse() rejected @p line.
 */
static bool rejects(const char *line)
{
    char payload[64];
    return !proto_parse(line, payload, sizeof payload);
}

/** @brief Run every check; exit status 0 only if all passed. */
int main(void)
{
    char buf[64];

    /* checksum: XOR of the payload bytes */
    CHECK(proto_checksum("A", 1) == 0x41);
    CHECK(proto_checksum("AA", 2) == 0x00);
    CHECK(proto_checksum("INIT", 4) == 0x1A);
    CHECK(proto_checksum("BAUD,115200", 11) ==
          (0x42 ^ 0x41 ^ 0x55 ^ 0x44 ^ 0x2C ^ 0x31 ^ 0x31 ^ 0x35 ^ 0x32 ^ 0x30 ^ 0x30));

    /* build: '$', payload, '*', two upper-case hex digits, LF - same bytes as build_frame() */
    CHECK(proto_build(buf, sizeof buf, "A") == 6 && strcmp(buf, "$A*41\n") == 0);
    CHECK(proto_build(buf, sizeof buf, "INIT") == 9 && strcmp(buf, "$INIT*1A\n") == 0);
    CHECK(proto_build(buf, 6, "A") == -1);                 /* no room for the NUL */

    /* parse: accepts a built frame (minus the LF, which uart_link strips) and lower-case hex */
    CHECK(proto_parse("$A*41", buf, sizeof buf) && strcmp(buf, "A") == 0);
    CHECK(proto_parse("$INIT*1a", buf, sizeof buf) && strcmp(buf, "INIT") == 0);
    CHECK(proto_build(buf, sizeof buf, "ACK,BAUD,230400") > 0);
    buf[strlen(buf) - 1] = '\0';                           /* drop the LF */
    char payload[64];
    CHECK(proto_parse(buf, payload, sizeof payload) && strcmp(payload, "ACK,BAUD,230400") == 0);

    /* parse: rejects everything that is not a valid frame (cases of test_protocol.py) */
    CHECK(rejects(""));
    CHECK(rejects("I (123) main: Tarea2 BME688 firmware ready"));   /* ESP_LOG line */
    CHECK(rejects("$A*42"));                               /* wrong checksum */
    CHECK(rejects("$A*4"));                                /* truncated checksum */
    CHECK(rejects("$*00"));                                /* empty payload */
    CHECK(rejects("A*41"));                                /* missing '$' */
    CHECK(rejects("$A*ZZ"));                               /* non-hex checksum */
    CHECK(rejects("\xff$A*41"));                           /* boot garbage prefix */
    CHECK(rejects("$A*41x"));                              /* trailing garbage */
    CHECK(!proto_parse("$A*41", buf, 1));                  /* payload does not fit */

    /* split: fields in order, ',' replaced by NUL, fields beyond max_fields dropped */
    char *fields[4];
    char baud[] = "BAUD,115200";
    CHECK(proto_split(baud, fields, 4) == 2 && strcmp(fields[0], "BAUD") == 0 &&
          strcmp(fields[1], "115200") == 0);
    char many[] = "a,b,c";
    CHECK(proto_split(many, fields, 2) == 2 && strcmp(fields[1], "b") == 0);
    char empty_tail[] = "ACK,";
    CHECK(proto_split(empty_tail, fields, 4) == 2 && fields[1][0] == '\0');

    if (s_failures == 0) {
        printf("test_protocol_c: all checks passed\n");
    }
    return s_failures == 0 ? 0 : 1;
}
