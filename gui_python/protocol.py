"""@file protocol.py
@brief Frame layer for the ESP32 <-> PC serial link (framing unchanged from Tarea 1).

Frame format (ASCII, one frame per line), identical to esp32_firmware/main/protocol.c:

    $<payload>*<XX>        (terminated by LF)

- `payload`: comma-separated fields; the first one is the message type ("SMP", "ACK", ...)
- `XX`: two upper-case hex digits = XOR of every payload byte (between '$' and '*')

Only framing, checksums and the message type names live here. The fields of each message
are documented in README.md ("Protocolo"), decoded by messages.py and routed by
main_window.py. Keep this file and protocol.c in sync.
"""
from __future__ import annotations

from typing import List, Optional

## ESP32 -> PC: one acquisition: seq, t_ms, the selected variables and the processing results.
MSG_SMP = "SMP"
## ESP32 -> PC: temperature peak event (value, threshold applied, time).
MSG_PEAK = "PEAK"
## ESP32 -> PC: command accepted (ACK,CFG echoes the configuration actually applied).
MSG_ACK = "ACK"
## ESP32 -> PC: command rejected or bad frame.
MSG_ERR = "ERR"
## PC -> ESP32: complete runtime configuration (rate, variables, average, peaks), applied atomically.
CMD_CFG = "CFG"
## PC -> ESP32: reset to defaults and (re)start acquisition.
CMD_INIT = "INIT"
## PC -> ESP32: change the speed of the link itself (answered at the *old* speed).
CMD_BAUD = "BAUD"


def checksum(payload: str) -> int:
    """@brief XOR of every byte of @p payload.

    @param payload  Payload text without '$', '*' or checksum; must be ASCII.
    @return Checksum in the range 0..255.
    @throws UnicodeEncodeError if @p payload contains non-ASCII characters.
    """
    cs = 0
    for b in payload.encode("ascii"):
        cs ^= b
    return cs


def build_frame(payload: str) -> bytes:
    """@brief Wrap a payload as a complete frame, ready for serial.write().

    @param payload  Payload text such as "BAUD,115200".
    @return ASCII bytes `$payload*XX` followed by a newline.
    """
    return f"${payload}*{checksum(payload):02X}\n".encode("ascii")


def parse_frame(line: str) -> Optional[List[str]]:
    """@brief Validate one received line and split its payload into fields.

    Hex digits of the checksum may be in either case; surrounding whitespace and CR/LF are
    ignored.

    @param line  One line as read from the serial port.
    @return The payload fields, e.g. ["ACK", "INIT", "2.0"], or None for anything that is
            not a well-formed frame with a correct checksum (bootloader output, ESP_LOG
            lines, corrupted bytes) so callers can count and skip it.
    """
    line = line.strip()
    if len(line) < 5 or line[0] != "$" or line[-3] != "*":
        return None
    payload, hex_cs = line[1:-3], line[-2:]
    if not payload:
        return None
    try:
        expected = int(hex_cs, 16)
        actual = checksum(payload)
    except (ValueError, UnicodeEncodeError):
        return None
    if actual != expected:
        return None
    return payload.split(",")
