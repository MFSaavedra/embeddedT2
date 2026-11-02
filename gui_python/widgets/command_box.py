"""@file command_box.py
@brief Manual command entry, for testing (T2 spec 6.7: "enviar una configuración inválida").

The configuration panel can only build valid commands, so this box is how an invalid one is
sent on purpose: the payload typed here goes out framed with a correct checksum (e.g.
"CFG,sampling_hz=3,..." or "HOLA"), and the ESP32's ERR reply shows up in the status bar
and, for a CFG, in the configuration panel.
"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QGroupBox, QHBoxLayout, QLineEdit, QPushButton

## Example shown in the empty entry: a CFG with an invalid rate.
PLACEHOLDER = "p. ej. CFG,sampling_hz=3,variables=T,avg_enabled=0,window_s=10,peak_enabled=0,threshold_c=28.0"


class CommandBox(QGroupBox):
    """@brief A line entry and an Enviar button."""

    ## User sent a payload (stripped, never empty).
    command_entered = pyqtSignal(str)

    def __init__(self, parent=None):
        """@brief Build the entry and the button.

        @param parent  Optional QWidget parent.
        """
        super().__init__("Comando manual (pruebas)", parent)
        ## Payload to send, without '$' or checksum.
        self.entry = QLineEdit()
        self.entry.setPlaceholderText(PLACEHOLDER)
        ## Sends the entry (as does Enter).
        self.send_btn = QPushButton("Enviar")

        row = QHBoxLayout(self)
        row.addWidget(self.entry, 1)
        row.addWidget(self.send_btn)

        # Doxygen would read self._emit as an attribute.
        # @cond
        self.send_btn.clicked.connect(self._emit)
        self.entry.returnPressed.connect(self._emit)
        # @endcond

    def _emit(self) -> None:
        """@brief Emit command_entered with the entry's text, if there is any."""
        text = self.entry.text().strip()
        if text:
            self.command_entered.emit(text)
