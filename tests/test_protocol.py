"""@file test_protocol.py
@brief Unit tests for the frame layer (protocol.py). Run with: `pytest`

The expected values double as the reference for the firmware side: tests/firmware/
test_protocol_c.c checks protocol.c against the same bytes (see test_firmware_host.py).
"""
import protocol


def test_checksum_is_xor_of_payload_bytes():
    """@brief checksum() is the XOR of the ASCII codes, so a repeated byte cancels out."""
    assert protocol.checksum("A") == 0x41
    assert protocol.checksum("AA") == 0x00
    assert protocol.checksum("BAUD,115200") == (
        0x42 ^ 0x41 ^ 0x55 ^ 0x44 ^ 0x2C ^ 0x31 ^ 0x31 ^ 0x35 ^ 0x32 ^ 0x30 ^ 0x30
    )


def test_build_frame_format():
    """@brief build_frame() yields '$', payload, '*', two upper-case hex digits and LF."""
    assert protocol.build_frame("A") == b"$A*41\n"
    assert protocol.build_frame("INIT") == b"$INIT*1A\n"


def test_round_trip():
    """@brief A frame built by build_frame() parses back into the original fields."""
    payload = "ACK,BAUD,230400"
    line = protocol.build_frame(payload).decode()
    assert protocol.parse_frame(line) == ["ACK", "BAUD", "230400"]


def test_parse_accepts_crlf_and_lowercase_hex():
    """@brief parse_frame() tolerates CR+LF line endings and lower-case checksum digits."""
    assert protocol.parse_frame("$A*41\r\n") == ["A"]
    assert protocol.parse_frame("$INIT*1a") == ["INIT"]  # I^N^I^T = 0x1A


def test_parse_rejects_garbage():
    """@brief parse_frame() returns None for everything that is not a valid frame."""
    assert protocol.parse_frame("") is None
    assert protocol.parse_frame("I (123) main: Tarea2 BME688 firmware ready") is None  # ESP_LOG line
    assert protocol.parse_frame("$A*42") is None       # wrong checksum
    assert protocol.parse_frame("$A*4") is None        # truncated checksum
    assert protocol.parse_frame("$*00") is None        # empty payload
    assert protocol.parse_frame("A*41") is None        # missing '$'
    assert protocol.parse_frame("$A*ZZ") is None       # non-hex checksum
    assert protocol.parse_frame("\x00\xff$A*41") is None  # boot garbage prefix
