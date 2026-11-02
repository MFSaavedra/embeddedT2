"""@file serial_worker.py
@brief Background serial I/O so the GUI thread never blocks (T2 spec 4, "Robustez": never block the GUI while reading the port).

SerialWorker owns the pyserial port. Its read loop runs in a QThread and talks to the GUI
only through Qt signals (thread-safe, delivered on the GUI thread). Writes are serialised
with a lock so any widget may call send() directly from the GUI thread.

Anything that reconfigures the port instead of writing to it - request_baud() - is queued
and applied by the read loop between two reads, because the loop is normally blocked inside
readline() and reconfiguring underneath it corrupts that read.
"""
from __future__ import annotations

import os
import threading
import time
from typing import List, Optional, Tuple

import serial
from PyQt5.QtCore import QThread, pyqtSignal
from serial.tools import list_ports

import protocol

## Seconds EN is held low when resetting the board after opening the port.
RESET_PULSE_S = 0.1
## Seconds given to the board after the reset pulse to reach app_main() before `connected`
## is emitted. Boot takes ~0.3 s including the ROM/bootloader logs; 1 s leaves margin.
BOOT_WAIT_S = 1.0
## Seconds waited before switching speed, so the board can finish emitting (at the old
## speed) whatever was queued behind the ACK that authorised the switch.
BAUD_SETTLE_S = 0.05


def available_ports() -> List[Tuple[str, str]]:
    """@brief Serial ports currently present, USB-serial adapters first.

    Legacy motherboard ports (/dev/ttyS0, COM1) open without error and then just swallow
    everything, so they are listed after any USB adapter: with the ESP32 plugged in, its
    CP2102 is the preselected entry in the connection panel and its label says so.

    @return (device, label) pairs such as
            ("/dev/ttyUSB0", "/dev/ttyUSB0 — Silicon Labs CP2102 USB to UART Bridge
            Controller") or ("/dev/ttyS0", "/dev/ttyS0"); empty if no port is present.
    """
    ports = list_ports.comports()
    usb = sorted((p for p in ports if p.vid is not None), key=lambda p: p.device)
    other = sorted((p for p in ports if p.vid is None), key=lambda p: p.device)
    return [(p.device, _port_label(p)) for p in usb + other]


def _port_label(info) -> str:
    """@brief Human-readable combo entry for one port: "<device> — <manufacturer product>".

    Falls back to pyserial's description when the USB product string is missing (Windows)
    and to the bare device name when even that is uninformative (pyserial reports "ttyS0"
    or "n/a" for legacy ports).

    @param info  A serial.tools.list_ports_common.ListPortInfo.
    @return The label; the device name alone if nothing better is known.
    """
    what = info.product or info.description or ""
    if what in ("n/a", os.path.basename(info.device)):
        what = ""
    if info.manufacturer and info.manufacturer not in what:
        what = f"{info.manufacturer} {what}".strip()
    return f"{info.device} — {what}" if what else info.device


class SerialWorker(QThread):
    """@brief Owns the serial port and runs the read loop in its own thread.

    Lifecycle: open() starts run() in the background, which first resets the board (see
    _reset_board()), waits BOOT_WAIT_S for it to boot and emits connected, then emits
    frame_received / bad_line for every line until close() is called or the port fails.
    send() and request_baud() may be called from any thread while the port is open.
    """

    ## Fields of a valid frame, e.g. ["ACK", "INIT", "2.0"] (see protocol.parse_frame()).
    frame_received = pyqtSignal(list)
    ## A received line that failed protocol.parse_frame(), CR/LF stripped.
    bad_line = pyqtSignal(str)
    ## Emitted once the port is open and the board has been reset and given BOOT_WAIT_S to
    ## boot, i.e. when it is ready to receive commands: (port, baud).
    connected = pyqtSignal(str, int)
    ## Emitted when the read loop ends, whether by close() or by an I/O error.
    disconnected = pyqtSignal()
    ## The port is now running at this speed, after a request_baud() took effect.
    baud_changed = pyqtSignal(int)
    ## Human-readable message for the status bar.
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        """@brief Create the worker without opening any port.

        @param parent  Optional QObject parent.
        """
        super().__init__(parent)
        ## Open pyserial port, or None while disconnected.
        self._ser: Optional[serial.Serial] = None
        ## Serialises send() calls coming from different threads.
        self._write_lock = threading.Lock()
        ## Set by close() so run() exits at the next read timeout.
        self._stop = threading.Event()
        ## Speed requested by request_baud(), applied by the read loop; None when idle.
        self._pending_baud: Optional[int] = None
        ## Guards _pending_baud between the GUI thread and the read loop.
        self._baud_lock = threading.Lock()

    # ------------------------------------------------------------ GUI-thread API

    def open(self, port: str, baud: int) -> bool:
        """@brief Open the port and start the read loop.

        Returns as soon as the port is open; the board reset and boot wait happen in run(),
        so connected arrives roughly BOOT_WAIT_S later via the signal, not before this
        returns.

        @param port  Device name, e.g. "/dev/ttyUSB0" or "COM3".
        @param baud  Baud rate; must match LINK_BAUD in the firmware.
        @return True if the port was opened (connected will be emitted); False if the
                worker is already running or the port could not be opened (error is
                emitted).
        """
        if self.isRunning():
            return False
        try:
            self._ser = serial.Serial(port, baudrate=baud, timeout=0.1)
        except (serial.SerialException, OSError, ValueError) as exc:
            self.error.emit(f"No se pudo abrir {port}: {exc}")
            return False
        self._stop.clear()
        self.start()
        return True

    def close(self) -> None:
        """@brief Stop the read loop and close the port.

        Blocks up to 2 s for the thread to finish, then closes the port whether or not it
        did: readline() can sit on a byte stream that never yields a newline (the board
        talking at another speed), so the wait is bounded and the reader is written to
        tolerate having the port closed under it (see _pump_line()). Safe to call when not
        connected.
        """
        self._stop.set()
        if self.isRunning():
            self.wait(2000)
        self._close_port()

    def request_baud(self, baud: int) -> None:
        """@brief Ask the read loop to switch the open port to @p baud.

        The switch is deferred instead of applied here: run() is normally blocked inside
        readline(), and reconfiguring the port under it would corrupt that read. The loop
        picks the request up within one read timeout (0.1 s) and emits baud_changed once
        the port is running at the new speed.

        Only the PC side changes. The firmware must have been told separately (BAUD
        command) and must already have switched, which is what its ACK means.

        @param baud  New speed; must be one the firmware accepts.
        """
        with self._baud_lock:
            self._pending_baud = baud

    def send(self, payload: str) -> bool:
        """@brief Frame and transmit a command payload.

        @param payload  Payload text such as "BAUD,115200" (see protocol.py).
        @return True if the frame was written; False if not connected or the write failed
                (error is emitted in both cases).
        """
        ser = self._ser
        if ser is None or not ser.is_open:
            self.error.emit("No conectado")
            return False
        try:
            with self._write_lock:
                ser.write(protocol.build_frame(payload))
        except (serial.SerialException, OSError) as exc:
            self.error.emit(f"Error al enviar: {exc}")
            return False
        return True

    # --------------------------------------------------------------- thread body

    def run(self) -> None:
        """@brief Thread body: reset the board, wait for it to boot, then read lines until
        stopped or the port fails.

        Every line is passed through protocol.parse_frame(): valid frames are emitted as
        frame_received, everything else as bad_line. Lines received during the boot wait
        (ROM output at 115200, bootloader and app logs) take the same path, so they show
        up in the rejected counter like any other log line. On an I/O error (typically an
        unplugged cable) error is emitted and the loop ends. The port is always closed and
        disconnected emitted on exit.
        """
        ser = self._ser
        try:
            self._run_until_stopped(ser)
        except Exception as exc:        # noqa: BLE001 - the contract is that run() never raises
            self.error.emit(f"Error interno del hilo serial: {exc}")
        finally:
            self._close_port()
            self.disconnected.emit()

    def _run_until_stopped(self, ser: serial.Serial) -> None:
        """@brief Body of run(): reset, wait for boot, then read until stopped.

        Split out so run() can be a single try/finally that lets nothing escape.

        @param ser  The open port.
        """
        self._reset_board(ser)
        boot_deadline = time.monotonic() + BOOT_WAIT_S
        while not self._stop.is_set() and time.monotonic() < boot_deadline:
            if not self._pump_line(ser):
                return
        if self._stop.is_set():
            return
        self.connected.emit(ser.port, ser.baudrate)
        while not self._stop.is_set():
            if not self._pump_line(ser):
                return
            self._apply_pending_baud(ser)

    def _reset_board(self, ser: serial.Serial) -> None:
        """@brief Pulse EN low through the dev board's DTR/RTS auto-reset circuit.

        Same sequence as esptool's hard reset: DTR deasserted keeps IO0 high so the chip
        boots the firmware (not the ROM download mode) while RTS is asserted for
        RESET_PULSE_S to pull EN low. Merely opening the port also toggles both lines,
        but the OS drives them in an order and with a timing that leave the ESP32 hung
        most of the time on Linux with a CP2102 board (measured 1-4 usable connects out
        of 10); an explicit pulse boots it every time. Both lines are left deasserted (EN
        and IO0 high). A port without modem lines is reported but not fatal: the user can
        still press the EN button.

        @param ser  The open port.
        """
        try:
            ser.dtr = False
            ser.rts = True
            time.sleep(RESET_PULSE_S)
            ser.rts = False
        except (serial.SerialException, OSError) as exc:
            self.error.emit(f"No se pudo reiniciar el ESP32 (pulsa EN en la placa): {exc}")

    def _pump_line(self, ser: serial.Serial) -> bool:
        """@brief Read one line (or time out) and emit frame_received / bad_line for it.

        @param ser  The open port.
        @return False if the port failed (error has been emitted), True otherwise.
        """
        try:
            raw = ser.readline()            # b"" on timeout
        except Exception as exc:            # noqa: BLE001 - see below
            # Typical cause: the cable was unplugged. TODO(PY1): reconnect policy.
            # Deliberately broad: a port that dies mid-read does not only raise
            # SerialException. Observed on a real CP2102 when close() closed the port
            # while this thread was inside readline(): pyserial then calls os.read() with
            # a None file descriptor and raises TypeError, which used to escape run().
            self.error.emit(f"Conexión perdida: {exc}")
            return False
        if raw:
            line = raw.decode("ascii", errors="replace")
            fields = protocol.parse_frame(line)
            if fields is None:
                self.bad_line.emit(line.rstrip())
            else:
                self.frame_received.emit(fields)
        return True

    def _apply_pending_baud(self, ser: serial.Serial) -> None:
        """@brief Apply a request_baud() if one is pending (called between reads).

        Waits BAUD_SETTLE_S first so the board can finish sending, at the old speed, the log
        line that trails the ACK, then drops those bytes: whatever is in the input buffer at
        this point was clocked in at a speed that no longer applies.

        A failure is reported but is not fatal: the port keeps its previous speed, which is
        also the speed the firmware falls back to when no frame reaches it (LINK_BAUD_REVERT_MS),
        so the link repairs itself instead of dying.

        @param ser  The open port.
        """
        with self._baud_lock:
            baud, self._pending_baud = self._pending_baud, None
        if baud is None or baud == ser.baudrate:
            return
        time.sleep(BAUD_SETTLE_S)
        try:
            ser.reset_input_buffer()
            ser.baudrate = baud
        except (serial.SerialException, OSError, ValueError) as exc:
            self.error.emit(f"No se pudo cambiar a {baud} baud: {exc}")
            return
        self.baud_changed.emit(baud)

    def _close_port(self) -> None:
        """@brief Close and forget the port, swallowing any error from a dead device."""
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:   # noqa: BLE001 - closing a dead port must never raise
                pass
